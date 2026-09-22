# Security Policy

## Supported Versions

| Version | Supported |
| :--- | :--- |
| 0.0.x | :white_check_mark: Supported |

---

## Reporting a Vulnerability

If you discover a security vulnerability in **Sieve Lens**, please **do not**
disclose it in a public Issue or Pull Request. Instead, report it privately by
emailing **neguse.cat@gmail.com** with the following information, if possible:

### Vulnerability Report Template

- **Affected component(s)**:  
  (例: `sieve_lens.py`, `SieveLensEngine.observe()`)
- **Version(s) impacted**:  
  (例: v0.0.1)
- **Description**:  
  (脆弱性の概要)
- **Steps to reproduce**:  
  (再現手順・最小限のPoCファイル)
- **Potential impact**:  
  (想定される影響・深刻度)
- **Suggested fix (optional)**:  
  (可能であれば修正案)

---

## Scope Note

Sieve Lens is an **observation engine**, not a sandbox or a security
boundary. It does not execute, render, or interpret the documents it reads.
It performs character-level and structural scanning only.

The engine is not designed to prevent attacks; it is designed to make
invisible content visible to a human reviewer.

---

## Response Expectations

This project is developed and maintained part-time by a solo developer who is
also a full-time student. Depending on timing, initial responses to
vulnerability reports or the release of a fix may take anywhere from a few
days to about a week.

We appreciate your patience if a response is delayed, and will do our best to
share status updates along the way. Thank you for helping keep this project's
community safe and for your understanding.