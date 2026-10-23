import { useQuery } from "@tanstack/react-query";
import { get } from "../api/client.js";
import Icon from "./Icon.jsx";

/** Invariant 8: while the active model is a mock, every portal shows this watermark.
 *  Fail-safe: if health cannot be read, the banner is shown. */
export default function MockBanner() {
  const { data, isError } = useQuery({ queryKey: ["health"], queryFn: () => get("/health"), staleTime: 60_000 });
  const isMock = isError || !data || data.model?.is_mock !== false;
  if (!isMock) return null;
  return (
    <div className="mock-banner" role="note" id="mock-model-banner">
      <Icon name="alert" size={14} />
      MOCK MODEL — NOT FOR CLINICAL USE
    </div>
  );
}
