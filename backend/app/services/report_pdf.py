"""PDF rendering for signed reports (fpdf2, pure Python).

Two variants from one context:
- patient:   plain language, the doctor's category, summary and recommendation, photos, sign-off. No AI numbers.
- clinician: adds the AI result (score, uncertainty, reasons), the review, the change summary, the difference map
             and the doctor's notes.
Both carry the disclaimer, and a watermark while the model is a mock (invariant 8).
"""
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from fpdf import FPDF
from fpdf.enums import MethodReturnValue, XPos, YPos

from app.core.config import settings

DISCLAIMER = "AI decision support - final assessment by the signing clinician."
INK, MUTED, FAINT, RULE = (26, 31, 44), (84, 92, 110), (130, 138, 155), (214, 219, 228)
ACCENT = (14, 124, 140)
TONES = {  # (strong, tint) per category, print-friendly
    "routine_monitoring": ((30, 138, 90), (228, 244, 236)),
    "shortened_interval": ((176, 112, 20), (252, 241, 222)),
    "specialist_referral": ((192, 57, 43), (250, 230, 227)),
}
CLINICIAN_LABEL = {
    "routine_monitoring": "Routine monitoring",
    "shortened_interval": "Shortened follow-up interval",
    "specialist_referral": "Specialist referral recommended",
}
PATIENT_LABEL = {
    "routine_monitoring": "No changes that need action now",
    "shortened_interval": "An earlier follow-up visit is recommended",
    "specialist_referral": "A specialist should examine this spot",
}
REASONS = {
    "low_image_quality": "image quality too low", "registration_uncertain": "visits could not be aligned reliably",
    "model_disagreement": "model uncertainty high", "out_of_distribution": "images unlike the training data",
    "model_error": "the model could not produce a result", "segmentation_low_confidence": "lesion outline uncertain",
    "ambiguous_prediction": "result on a category boundary",
}
SITES = {
    "head_neck": "Head and neck", "anterior_torso": "Front of torso", "posterior_torso": "Back",
    "lateral_torso": "Side of torso", "upper_extremity": "Arm or hand", "lower_extremity": "Leg or foot",
    "palms_soles": "Palm or sole", "oral_genital": "Oral or genital", "unknown": "Not recorded",
}


@dataclass
class ReportContext:
    hospital_name: str
    hospital_address: str | None
    report_number: str
    version: int
    supersedes_number: str | None
    patient_name: str
    mrn: str
    date_of_birth: date
    lesion_label: str | None
    anatomical_site: str | None
    final_category: str
    patient_summary: str
    recommendation: str
    doctor_notes: str | None
    signed_by: str
    signed_by_registration: str | None
    signed_at: datetime
    photos: list[tuple[date, bytes]] = field(default_factory=list)  # (visit date, JPEG thumbnail)
    # AI details (clinician copy only)
    model_name: str | None = None
    model_version: str | None = None
    is_mock: bool = False
    ai_category: str | None = None
    risk_score: float | None = None
    uncertainty_score: float | None = None
    referral_flag: bool = False
    is_baseline: bool = False
    reason_codes: list[str] = field(default_factory=list)
    review_decision: str | None = None
    review_reason: str | None = None
    change_summary: list[str] = field(default_factory=list)
    difference_map_png: bytes | None = None


@lru_cache(maxsize=1)
def _fonts() -> tuple[str | None, str | None]:
    """A Unicode TrueType pair if one exists; otherwise None (core Helvetica, Latin-1 only)."""
    candidates = [
        (settings.report_font_path, settings.report_font_bold_path),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ]
    for regular, bold in candidates:
        if regular and Path(regular).exists():
            return regular, bold if bold and Path(bold).exists() else regular
    return None, None


def _local(dt: datetime) -> str:
    tz = ZoneInfo(settings.display_timezone)
    return dt.astimezone(tz).strftime("%d %b %Y, %H:%M ") + dt.astimezone(tz).tzname()


class _ReportPDF(FPDF):
    def __init__(self, ctx: ReportContext, variant: str):
        super().__init__(format="A4", unit="mm")
        self.ctx, self.variant = ctx, variant
        regular, bold = _fonts()
        if regular:
            self.add_font("Body", "", regular)
            self.add_font("Body", "B", bold)
            self.family, self.unicode = "Body", True
        else:
            self.family, self.unicode = "helvetica", False
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(True, margin=22)
        self.set_title(f"{ctx.report_number} ({variant} copy)")
        self.set_author(ctx.hospital_name)
        self.set_creator("MelanoTrack")

    def t(self, s: str | None) -> str:
        s = s or ""
        return s if self.unicode else s.encode("latin-1", "replace").decode("latin-1")

    def font(self, size: float, bold: bool = False, color=INK):
        self.set_font(self.family, "B" if bold else "", size)
        self.set_text_color(*color)

    def header(self):
        ctx = self.ctx
        self.font(14, True)
        self.cell(110, 7, self.t(ctx.hospital_name))
        self.font(9, True, ACCENT)
        self.cell(0, 7, "Skin lesion monitoring report", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.font(8, color=MUTED)
        self.cell(110, 5, self.t(ctx.hospital_address or ""))
        self.cell(0, 5, self.t(f"{ctx.report_number}  -  version {ctx.version}"), align="R",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.6)
        self.line(16, self.get_y() + 2, 194, self.get_y() + 2)
        self.ln(5)
        if ctx.is_mock:
            self.set_fill_color(252, 236, 200)
            self.font(8.5, True, (150, 90, 0))
            self.cell(0, 6, "MOCK MODEL - NOT FOR CLINICAL USE", align="C", fill=True,
                      new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            with self.rotation(35, 105, 160), self.local_context(fill_opacity=0.10):
                self.font(54, True, (200, 120, 0))
                self.text(28, 172, "MOCK MODEL")
            self.ln(2)

    def footer(self):
        self.set_y(-16)
        self.set_draw_color(*RULE)
        self.set_line_width(0.2)
        self.line(16, self.get_y(), 194, self.get_y())
        self.font(7.5, color=FAINT)
        self.cell(140, 8, DISCLAIMER)
        self.cell(0, 8, f"{'Patient' if self.variant == 'patient' else 'Clinician'} copy  -  page {self.page_no()}/{{nb}}",
                  align="R")

    def heading(self, text: str):
        self.ln(3)
        self.font(8.5, True, MUTED)
        self.cell(0, 6, self.t(text.upper()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def paragraph(self, text: str, size: float = 10.5, color=INK):
        self.font(size, color=color)
        self.multi_cell(0, 5.6, self.t(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def facts(self, rows: list[tuple[str, str]]):
        for i in range(0, len(rows), 2):
            for label, value in rows[i:i + 2]:
                self.font(8, color=FAINT)
                self.cell(26, 6, self.t(label))
                self.font(10, True)
                self.cell(63, 6, self.t(value))
            self.ln(6)

    def result_box(self, title: str, lines: list[str], category: str | None):
        strong, tint = TONES.get(category, ((84, 92, 110), (238, 240, 244)))
        self.font(14, True)
        height = 6 + 5 + self.multi_cell(168, 7, self.t(title), dry_run=True, output=MethodReturnValue.HEIGHT)
        self.font(9.5)
        height += sum(self.multi_cell(168, 5, self.t(line), dry_run=True, output=MethodReturnValue.HEIGHT)
                      for line in lines)
        if self.get_y() + height + 4 > 297 - 22:
            self.add_page()
        top = self.get_y() + 2
        self.set_fill_color(*tint)
        self.rect(16, top, 178, height, style="F")
        self.set_fill_color(*strong)
        self.rect(16, top, 2.5, height, style="F")
        self.set_xy(22, top + 3)
        self.font(8, True, MUTED)
        self.cell(0, 5, "RESULT", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_x(22)
        self.font(14, True, strong)
        self.multi_cell(168, 7, self.t(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        for line in lines:
            self.set_x(22)
            self.font(9.5, color=MUTED)
            self.multi_cell(168, 5, self.t(line), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_y(top + height + 2)

    def photos(self, photos: list[tuple[date, bytes]]):
        shown = photos[-6:]
        width = min(40.0, (178 - 4 * (len(shown) - 1)) / len(shown))
        if self.get_y() + width * 0.75 + 10 > 297 - 22:
            self.add_page()
        y = self.get_y()
        for i, (visit_date, jpeg) in enumerate(shown):
            x = 16 + i * (width + 4)
            self.image(io.BytesIO(jpeg), x=x, y=y, w=width)
            self.set_xy(x, y + width * 0.75 + 1)
            self.font(8, color=MUTED)
            self.cell(width, 5, visit_date.strftime("%d %b %Y"), align="C")
        self.set_y(y + width * 0.75 + 8)


def render(ctx: ReportContext, variant: str) -> bytes:
    if variant not in ("patient", "clinician"):
        raise ValueError(variant)
    pdf = _ReportPDF(ctx, variant)
    pdf.add_page()
    pdf.font(9, True, ACCENT)
    pdf.cell(0, 6, "PATIENT COPY" if variant == "patient" else "CLINICIAN COPY - contains AI details",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.facts([
        ("Patient", ctx.patient_name), ("MRN", ctx.mrn),
        ("Date of birth", ctx.date_of_birth.strftime("%d %b %Y")), ("Report date", _local(ctx.signed_at)[:11]),
        ("Lesion", ctx.lesion_label or "-"), ("Body site", SITES.get(ctx.anatomical_site, ctx.anatomical_site or "-")),
    ])
    if ctx.supersedes_number:
        pdf.paragraph(f"This version replaces report {ctx.supersedes_number}.", 9, MUTED)

    if variant == "patient":
        pdf.result_box(PATIENT_LABEL[ctx.final_category], [], ctx.final_category)
    else:
        lines = [f"Doctor's category: {CLINICIAN_LABEL[ctx.final_category]}"]
        if ctx.model_name:
            if ctx.is_baseline:
                ai = "baseline only (one visit), no risk estimate"
            elif ctx.referral_flag:
                ai = "referred, no category (" + ", ".join(REASONS.get(r, r) for r in ctx.reason_codes) + ")"
            else:
                ai = f"{CLINICIAN_LABEL.get(ctx.ai_category, ctx.ai_category)}"
            if ctx.risk_score is not None:
                ai += f"; risk score {ctx.risk_score:.2f}"
            if ctx.uncertainty_score is not None:
                ai += f"; uncertainty {ctx.uncertainty_score:.2f}"
            lines.append(f"AI result: {ai}")
            if ctx.review_decision:
                lines.append(f"Review: {ctx.review_decision}" + (f" - {ctx.review_reason}" if ctx.review_reason else ""))
        pdf.result_box(CLINICIAN_LABEL[ctx.final_category], lines, ctx.final_category)

    pdf.heading("Summary")
    pdf.paragraph(ctx.patient_summary)
    pdf.heading("Recommendation")
    pdf.paragraph(ctx.recommendation)
    if ctx.photos:
        pdf.heading("Photos of this spot")
        pdf.photos(ctx.photos)

    if variant == "clinician":
        if ctx.change_summary:
            pdf.heading("AI change summary")
            for s in ctx.change_summary:
                pdf.paragraph(f"-  {s}", 10)
        if ctx.difference_map_png:
            pdf.heading("Difference map (first vs latest visit, after alignment)")
            if pdf.get_y() + 75 > 297 - 22:
                pdf.add_page()
            pdf.image(io.BytesIO(ctx.difference_map_png), x=16, w=95)
            pdf.ln(2)
        if ctx.doctor_notes:
            pdf.heading("Doctor's notes")
            pdf.paragraph(ctx.doctor_notes, 10)
        if ctx.model_name:
            pdf.heading("Model")
            pdf.paragraph(f"{ctx.model_name} {ctx.model_version}" + (" (mock, not for clinical use)" if ctx.is_mock
                                                                     else ""), 9.5, MUTED)

    pdf.ln(4)
    if pdf.get_y() > 297 - 45:
        pdf.add_page()
    pdf.set_draw_color(*RULE)
    pdf.line(16, pdf.get_y(), 110, pdf.get_y())
    pdf.ln(2)
    reg = f" (Reg. no. {ctx.signed_by_registration})" if ctx.signed_by_registration else ""
    pdf.paragraph(f"Electronically signed by {ctx.signed_by}{reg}", 10)
    pdf.paragraph(f"on {_local(ctx.signed_at)}", 9.5, MUTED)
    return bytes(pdf.output())
