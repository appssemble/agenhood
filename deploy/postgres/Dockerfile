# Bundled Postgres that derives POSTGRES_USER/PASSWORD/DB from the single
# canonical DATABASE_URL (the same SQLAlchemy async DSN the app services consume),
# so the whole stack shares ONE connection-string secret. The parse wrapper is
# baked into the image rather than bind-mounted — same Coolify single-file
# repo-bind-mount pitfall the traefik/searxng images avoid.
# Build context is the monorepo root (matches the other services + Base Directory `/`).
FROM postgres:16
COPY deploy/postgres/parse-db-url-entrypoint.sh /usr/local/bin/parse-db-url-entrypoint.sh
RUN chmod +x /usr/local/bin/parse-db-url-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/parse-db-url-entrypoint.sh"]
CMD ["postgres"]
