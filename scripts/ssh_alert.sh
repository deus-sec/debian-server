cat > /usr/local/bin/ssh_alert.sh << 'EOF'
#!/bin/bash
cat > /tmp/ssh_alert.txt << ALERTEOF
PAM_TYPE=${PAM_TYPE}
PAM_USER=${PAM_USER}
PAM_RHOST=${PAM_RHOST}
DATE=$(date '+%Y-%m-%d %H:%M:%S')
ALERTEOF
EOF
chmod +x /usr/local/bin/ssh_alert.sh
