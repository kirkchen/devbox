# Security Behavior

## Credential Handling
- NEVER hardcode secrets — always use environment variables or secret managers
- If you encounter credentials in code or config, STOP and warn the user immediately
- If a secret may have been exposed, remind the user to rotate it
- Displaying partial secrets for identification is OK (e.g., `sk-...abc123`)
- Piping secrets to commands without displaying them is OK (e.g., `kubectl get secret ... | base64 -d | curl ...`)

## Sensitive Files
- Do NOT read or modify: .env*, ~/.ssh/*, ~/.aws/*, ~/.kube/config, **/secrets/**
- If asked to work with these files, explain the risk and ask for explicit confirmation

## Code Security
- Validate all user inputs at system boundaries
- Use parameterized queries (never string concatenation for SQL)
- Sanitize HTML output to prevent XSS
- Error messages must not leak internal paths, stack traces, or credentials
