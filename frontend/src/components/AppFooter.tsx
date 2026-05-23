const YEAR = new Date().getFullYear();

export default function AppFooter() {
  return (
    <footer className="site-footer">
      <div className="footer-inner">
        <div className="footer-columns">
          <div className="footer-col footer-col-wide">
            <h3 className="footer-heading">Tool description</h3>
            <div className="footer-description">
              <p className="footer-text">
                The <strong>AI-Powered Discrepancy Analysis &amp; Investigation Platform</strong>{" "}
                is an intelligent monitoring solution designed to identify, analyze, and explain
                data inconsistencies across enterprise business processes.
              </p>
              <p className="footer-text">
                The platform continuously validates whether critical business transactions are
                properly synchronized across connected systems and automatically detects missing
                records, mismatched information, processing failures, and data integrity issues.
              </p>
              <p className="footer-text">
                Using AI-powered investigation agents, the solution goes beyond simple comparison
                logic by performing automated root-cause analysis, interpreting system behavior,
                correlating related events, and generating business-friendly explanations with
                recommended next steps.
              </p>
              <p className="footer-text">
                The platform transforms complex technical discrepancies into actionable operational
                insights, helping business and support teams reduce manual investigation effort,
                accelerate issue resolution, and improve overall process reliability.
              </p>
            </div>
          </div>
          <div className="footer-col">
            <h3 className="footer-heading">Contact us</h3>
            <p className="footer-text">
              For demos, integrations, or enterprise deployment, reach out through
              your Turiaixis representative or the contact channel your organization
              uses for vendor engagement.
            </p>
          </div>
        </div>

        <div className="footer-divider" role="separator" />

        <div className="footer-bottom">
          <p className="footer-copyright">© {YEAR} Turiaixis</p>
          <div className="footer-logo-card">
            <img
              src="/turiaixis-logo.png"
              alt="Turiaixis — Speed is easy, Precision is earned"
              className="footer-logo"
              width={220}
              height={56}
            />
          </div>
        </div>
      </div>
    </footer>
  );
}
