# Responsibility Matrix

Roles:

- Application developer
- IT/deployment team
- Security team
- Business knowledge owner
- Platform administrator
- Management approver

RACI key:

- **R**: Responsible for doing the work
- **A**: Accountable for final approval/outcome
- **C**: Consulted
- **I**: Informed

| Area | Application developer | IT/deployment team | Security team | Business knowledge owner | Platform administrator | Management approver |
| --- | --- | --- | --- | --- | --- | --- |
| Application code | R/A | I | C | C | I | I |
| Frontend | R/A | C | C | C | I | I |
| Backend | R/A | C | C | C | I | I |
| CI workflows | R | C | C | I | I | I |
| Deployment approval | C | R | C | I | I | A |
| DNS | I | R/A | C | I | I | I |
| TLS | I | R | C/A | I | I | I |
| Firewall | I | R | C/A | I | I | I |
| VM maintenance | I | R/A | C | I | I | I |
| Docker | C | R/A | C | I | I | I |
| Database backups | C | R/A | C | I | I | I |
| Restore drills | C | R/A | C | I | C | I |
| GitHub secrets | I | R | C/A | I | I | I |
| SSH keys | I | R | C/A | I | I | I |
| Entra ID | C | R | A | I | C | I |
| Email provider | C | R | A | I | C | I |
| Monitoring | C | R/A | C | I | C | I |
| Incident response | C | R/A | C | C | R | I |
| Knowledge ownership | I | I | C | A | R | I |
| Article approval | I | I | C | A | R | I |
| User administration | C | I | C | I | R/A | I |
| Vulnerability remediation | R | C | A | I | I | I |

Do not assign company-specific names in this repository unless company governance has approved those assignments.
