import { Badge } from "../../components/ui.jsx";

export default function StaffStatus({ user }) {
  if (!user.is_active) return <Badge kind="danger" dot>Inactive</Badge>;
  if (user.locked_until && new Date(user.locked_until) > new Date()) return <Badge kind="warning" dot>Locked</Badge>;
  if (user.must_change_password) return <Badge kind="accent" dot>Awaiting first sign in</Badge>;
  return <Badge kind="success" dot>Active</Badge>;
}
