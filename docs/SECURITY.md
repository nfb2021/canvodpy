# Security Policy

## Supported Versions

canvodpy is currently in **beta** (pre-1.0 release). Security updates are provided for:

| Version | Supported          |
| ------- | ------------------ |
| 0.x.x   | :white_check_mark: |

Once canvodpy reaches v1.0.0, we will provide security updates for:
- The latest major version
- The previous major version (for 6 months after new major release)

## Reporting a Vulnerability

We take the security of canvodpy seriously. If you discover a security vulnerability, please follow these steps:

### 1. **Do Not** Open a Public Issue

Please **do not** report security vulnerabilities through public GitHub issues, discussions, or pull requests.

### 2. Report Privately

Report security vulnerabilities via one of these methods:

**Preferred:** Use GitHub's private vulnerability reporting:
- Go to https://github.com/nfb2021/canvodpy/security/advisories
- Click "Report a vulnerability"
- Fill in the details

**Alternative:** Email the maintainer directly:
- Email: nicolas.bader@tuwien.ac.at
- Include "SECURITY" in the subject line
- Provide a detailed description of the vulnerability

### 3. What to Include

Please include as much of the following information as possible:

- Type of vulnerability (e.g., buffer overflow, SQL injection, cross-site scripting)
- Full paths of source file(s) related to the vulnerability
- Location of the affected source code (tag/branch/commit or direct URL)
- Any special configuration required to reproduce the issue
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit it

### 4. Response Timeline

- **Initial Response:** Within 48 hours of report
- **Confirmation:** Within 7 days (whether we accept or decline the report)
- **Fix Timeline:** Depends on severity
  - Critical: 7 days
  - High: 30 days
  - Medium: 60 days
  - Low: 90 days

### 5. Disclosure Process

1. We will confirm receipt of your vulnerability report
2. We will investigate and validate the vulnerability
3. We will develop and test a fix
4. We will release a security advisory and patched version
5. We will credit you in the advisory (unless you prefer to remain anonymous)

## Security Best Practices for Users

### Data Handling

- **Do not process untrusted GNSS data files** without validation
- Be cautious when reading RINEX or SBF files from untrusted sources
- Validate input file paths to prevent directory traversal attacks

### Dependencies

- Keep canvodpy and its dependencies up to date
- Monitor security advisories:
  - GitHub Dependabot alerts (enabled for this repository)
  - PyPI security notifications
  - `pip-audit` or `safety` for your environment

### Credential Management

- **Never commit credentials** to version control
- Use environment variables or secure credential stores for:
  - Icechunk storage credentials (S3, Azure, GCS)
  - Ephemeris download credentials (if applicable)
  - Database connection strings

### Secure Configuration

- Follow the principle of least privilege for file system access
- Use read-only mounts for input data directories where possible
- Validate configuration files before use

## Known Security Considerations

### 1. File Format Parsers

canvodpy parses binary formats (SBF, RINEX). While we use robust parsing libraries:
- **Risk:** Maliciously crafted files could potentially cause crashes or unexpected behavior
- **Mitigation:** Always validate input files from untrusted sources

### 2. Cloud Storage

canvodpy can write to cloud storage (S3, Azure, GCS):
- **Risk:** Misconfigured credentials could expose data
- **Mitigation:** Use least-privilege IAM roles, enable encryption at rest

### 3. Dependency Chain

canvodpy depends on scientific Python packages (NumPy, SciPy, xarray, Zarr):
- **Risk:** Vulnerabilities in dependencies could affect canvodpy
- **Mitigation:** We monitor Dependabot alerts and update dependencies regularly

### 4. Code Execution

canvodpy loads Python configuration files:
- **Risk:** Configuration files can execute arbitrary Python code
- **Mitigation:** Only load configuration from trusted sources

## Security Features

### Current Implementation

- ✅ **OpenSSF Best Practices Badge** (Passing level) - [Project 12329](https://www.bestpractices.dev/projects/12329)
- ✅ Automated dependency scanning (Dependabot)
- ✅ OpenSSF Scorecard monitoring
- ✅ SPDX license compliance (REUSE 3.3)
- ✅ Pinned dependencies in `uv.lock`
- ✅ Pre-commit hooks (ruff linting & formatting, ty type checking, conventional commits)
- ✅ Continuous integration (8 workflows: tests, coverage, code quality, audit, FAIR checks)
- ✅ Static analysis (ruff with 50+ rule sets)
- ✅ Type checking (ty with type budget enforcement)
- ✅ Dynamic analysis (pytest test suite with coverage tracking)

### Planned Enhancements

- [ ] Input validation framework for GNSS data files
- [ ] Sandboxed configuration loading
- [ ] Formal security audit before v1.0 release
- [ ] Supply chain security (SLSA provenance)

## Vulnerability Disclosure Policy

We follow the principles of **Coordinated Vulnerability Disclosure**:

1. Researchers report vulnerabilities privately
2. We work with researchers to understand and fix the issue
3. We coordinate a public disclosure timeline
4. Credit is given to researchers (unless anonymous preferred)

We commit to:
- Responding promptly to vulnerability reports
- Keeping researchers informed of our progress
- Not taking legal action against researchers who follow this policy

## Security Acknowledgments

We would like to thank the following individuals for responsibly disclosing security issues:

*(None yet - be the first!)*

## Contact

For security-related questions or concerns:
- **Maintainer:** Nicolas François Bader
- **Email:** nicolas.bader@tuwien.ac.at
- **Affiliation:** Climate and Environmental Remote Sensing (CLIMERS), TU Wien

For general questions (non-security), please use:
- GitHub Discussions: https://github.com/nfb2021/canvodpy/discussions
- GitHub Issues: https://github.com/nfb2021/canvodpy/issues

---

**Last Updated:** March 30, 2026
