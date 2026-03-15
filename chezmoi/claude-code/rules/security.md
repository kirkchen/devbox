# Security Behavior

## Credential Handling
- NEVER read, display, or log secrets (API keys, passwords, tokens, private keys)
- If you encounter credentials in code or config, STOP and warn the user immediately
- NEVER hardcode secrets — always use environment variables or secret managers
- If a secret may have been exposed, remind the user to rotate it

## Sensitive Files
- Do NOT read or modify: .env*, ~/.ssh/*, ~/.aws/*, ~/.kube/config, **/secrets/**
- If asked to work with these files, explain the risk and ask for explicit confirmation

## Code Security
- Validate all user inputs at system boundaries
- Use parameterized queries (never string concatenation for SQL)
- Sanitize HTML output to prevent XSS
- Error messages must not leak internal paths, stack traces, or credentials
