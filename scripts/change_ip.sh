cat > /usr/local/bin/change-ip.sh << 'EOF'
#!/bin/bash
set -e
CURRENT_IP=$(hostname -I | awk '{print $1}')
echo "Detected IP: $CURRENT_IP"
read -p "Confirm? (y/n): " CONFIRM
[ "$CONFIRM" != "y" ] && read -p "Manual IP: " CURRENT_IP

echo "[1/4] Authelia..."
sed -i "s/domain: .*/domain: $CURRENT_IP/" /etc/authelia/configuration.yml
sed -i "s|authelia_url: .*|authelia_url: https://$CURRENT_IP:9091|" /etc/authelia/configuration.yml
sed -i "s|default_redirection_url: .*|default_redirection_url: https://$CURRENT_IP|" /etc/authelia/configuration.yml

echo "[2/4] SSL certificate..."
openssl req -x509 -newkey rsa:4096 -keyout /etc/authelia/key.pem -out /etc/authelia/cert.pem \
  -days 365 -nodes -subj "/CN=$CURRENT_IP" -addext "subjectAltName=IP:$CURRENT_IP" 2>/dev/null
chmod 644 /etc/authelia/key.pem /etc/authelia/cert.pem

echo "[3/4] Caddy..."
sed -i "s/https:\/\/[0-9.]*/https:\/\/$CURRENT_IP/g" /etc/caddy/Caddyfile

echo "[4/4] Restarting services..."
systemctl restart authelia && sleep 2 && systemctl restart caddy

echo "Done. Access: https://$CURRENT_IP"
EOF
chmod +x /usr/local/bin/change-ip.sh
