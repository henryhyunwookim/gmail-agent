# Zero Local .env Files & Cloud-Native Secret Resolution Policy

## Core Mandate
- **NEVER Propose, Create, or Mention Local `.env` Files**: Under NO circumstances should any `.env`, `.env.*`, or local environment configuration file be created, maintained, or suggested to the user.
- **Dynamic Google Cloud Secret Resolution**: All API keys, OAuth credentials, tokens, sensitive configuration, and database credentials MUST be fetched dynamically from Google Cloud Secret Manager (or Google Cloud Storage) at runtime.
- **Zero Local Environment Litter**:
  - Do NOT create `.env.example` or ask the user to populate local environment variables.
  - Do NOT instruct the user to "add X to your .env file" in READMEs, documentation, or chat responses.
  - Document configuration changes via Google Cloud Secret Manager (`gcloud secrets ...`), Cloud Run environment variables (`gcloud run services update ...`), or CLI runtime arguments.
- **Portability Across Machines**: Any repository must run out-of-the-box on any machine authenticated with `gcloud` without copying or creating credential files locally.
