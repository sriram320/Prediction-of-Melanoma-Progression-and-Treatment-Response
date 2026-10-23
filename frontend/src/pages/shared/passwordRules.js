// Mirrors backend app/core/security.py validate_new_password (the backend remains the authority).
export function passwordProblem(pw) {
  if (!pw) return "Enter a password";
  if (pw.length < 10) return "Use at least 10 characters";
  if (pw.length > 128) return "Use at most 128 characters";
  if (!/[A-Za-z]/.test(pw) || !/[0-9]/.test(pw)) return "Include at least one letter and one number";
  return null;
}
