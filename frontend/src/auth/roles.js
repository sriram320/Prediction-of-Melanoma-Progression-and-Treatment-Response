export const ROLE_LABELS = {
  super_admin: "Platform admin",
  hospital_admin: "Hospital admin",
  doctor: "Doctor",
  technician: "Technician",
  patient: "Patient",
};

export const HOME_BY_ROLE = {
  super_admin: "/admin",
  hospital_admin: "/hospital",
  doctor: "/doctor",
  technician: "/technician",
  patient: "/patient",
};

export function loginPathFor(roles = []) {
  if (roles.includes("patient")) return "/patient/login";
  if (roles.includes("super_admin")) return "/admin/login";
  return "/hospital/login";
}
