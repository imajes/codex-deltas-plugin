# Synthesize Config Rules

- `config-CLEAN.toml` is canonical and fully rewritten each run.
- `[features]` defaults come from `FeatureSpec.default_enabled`, not schema booleans inferred from old examples.
- Legacy keys stay commented in clean until code drops support.
- Removed keys are absent from clean and absent from proposed runtime.
- Runtime proposals preserve user intent and local integrations; they normalize only touched sections and required migrations.
- Use `default_permissions = "workspace"` plus `[permissions.workspace.network]` instead of legacy `[permissions.network]`.
- Keep section-link comments at the top of their section.
- Alphabetize sections and keys, including commented legacy keys.
- Separate platform-specific feature flags after the main feature list under a pseudo-section comment.
- Do not emit no-op reordering churn for `[tools.web_search]` or comment-only `[skills]` blocks.
