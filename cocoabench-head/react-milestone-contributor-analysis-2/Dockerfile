FROM ghcr.io/agent-infra/sandbox:latest

# Force web browsing by removing gh CLI
# Note: api.github.com blocking should be done at runtime if needed
RUN rm -f /usr/bin/gh /usr/local/bin/gh 2>/dev/null; exit 0
