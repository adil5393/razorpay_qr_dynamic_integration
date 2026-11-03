#!/bin/bash
# Starts a local PostgreSQL for the preview environment (data kept in /app/pgdata).
set -e
PGDATA=/app/pgdata
BIN=/usr/lib/postgresql/15/bin
DB_URL=$(grep '^DATABASE_URL=' /app/backend/.env | cut -d '=' -f2- | tr -d '"')
DB_USER=$(python3 -c "from urllib.parse import urlparse;print(urlparse('$DB_URL').username)")
DB_PASS=$(python3 -c "from urllib.parse import urlparse,unquote;print(unquote(urlparse('$DB_URL').password))")
DB_NAME=$(python3 -c "from urllib.parse import urlparse;print(urlparse('$DB_URL').path.lstrip('/'))")

if [ ! -x "$BIN/pg_ctl" ]; then
  apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql > /tmp/pg_install.log 2>&1
  service postgresql stop >/dev/null 2>&1 || true
fi

mkdir -p $PGDATA
chown -R postgres:postgres $PGDATA
chmod 700 $PGDATA

if [ ! -s $PGDATA/PG_VERSION ]; then
  su postgres -c "$BIN/initdb -D $PGDATA -A md5 --auth-local=peer -U postgres" >/dev/null
  echo "listen_addresses = 'localhost'" >> $PGDATA/postgresql.conf
fi

if ! su postgres -c "$BIN/pg_ctl -D $PGDATA status" >/dev/null 2>&1; then
  rm -f $PGDATA/postmaster.pid
  su postgres -c "$BIN/pg_ctl -D $PGDATA -l /tmp/postgres.log -w start" >/dev/null
fi

su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'\"" | grep -q 1 || \
  su postgres -c "psql -c \"CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASS'\"" >/dev/null
for db in $DB_NAME ${DB_NAME}_test; do
  su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='$db'\"" | grep -q 1 || \
    su postgres -c "createdb -O $DB_USER $db"
done
echo "postgres ready"
