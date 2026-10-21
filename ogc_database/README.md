docker exec -it postgres-vector psql -U postgres -d velocityadaptgeo \
  -c "SELECT * FROM ogc_processes LIMIT 10;"
