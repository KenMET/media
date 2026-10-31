# Project language policy

Use English for all project-authored documentation, contributor instructions, code comments, docstrings, model instructions, command-line output, operational logs, notifications, API/MCP explanations, test descriptions and configuration guidance. New contributions must follow this policy.

The website supports English and Chinese. Keep localized UI copy in its existing web localization system; do not add language selection to non-web interfaces. Preserve existing web language preferences.

Media content is data: original titles, user filenames, provider records, subtitle text, language markers and multilingual parsing fixtures must keep their meaning. English-only project copy must not disable Chinese filename recognition, change title identity, translate user media or weaken subtitle content verification. Where source fixtures or recognition patterns require non-English characters, encode those data literals explicitly and document their purpose in English. Do not conceal untranslated operational prose with Unicode escapes.

Ingestion and hardlink naming remain unchanged, including localized work names, season directories, extras directories and filenames. Preserve original-language metadata and existing Chinese-first naming behavior. Do not rename existing media, migrate state, change endpoints or change deployment credentials as part of language conversion. Historical reports must retain dates, identifiers, measured results, unresolved decisions and the distinction between local and deployed evidence.

Runtime code belongs under `src/media_mcp`, automated checks under `tests`, manual acceptance under `tests/manual`, current guidance under `docs`, and dated reports under `docs/history`.
