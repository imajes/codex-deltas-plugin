# Config Validation Rules

- `layout-only` mode validates sort order, section-link placement, and TOML parseability only.
- Full validation additionally checks feature defaults, removed-key absence, legacy-key removal from runtime, and named permissions profile migration.
- Validation is a separate concern from lifecycle classification and file synthesis.
