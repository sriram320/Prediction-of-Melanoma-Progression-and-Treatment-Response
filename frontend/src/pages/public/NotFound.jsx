import { Link } from "react-router-dom";
import Icon from "../../components/Icon.jsx";

export default function NotFound() {
  return (
    <div className="page-loading">
      <div className="card empty" style={{ width: "min(480px, 92vw)" }}>
        <div className="empty__icon"><Icon name="search" size={24} /></div>
        <h1 style={{ fontSize: "1.4rem", marginBottom: 8 }}>Page not found</h1>
        <p style={{ marginBottom: 20 }}>The page you are looking for does not exist or has moved.</p>
        <Link to="/" className="btn btn--primary" id="notfound-home-link">Go to the home page</Link>
      </div>
    </div>
  );
}
