cat > /usr/local/bin/export_csv.sh << 'EOF'
#!/bin/bash
DATE=$(date '+%Y%m%d_%H%M')
OUTPUT="/srv/exports/data_${DATE}.csv"
sudo -u postgres psql -d my_database -c "
  COPY (SELECT * FROM clients ORDER BY id)
  TO STDOUT WITH CSV HEADER
" > "$OUTPUT"
cp "$OUTPUT" /srv/exports/data_latest.csv
echo "$(date) - Export OK : $OUTPUT" >> /var/log/server_export.log
EOF
chmod +x /usr/local/bin/export_csv.sh
