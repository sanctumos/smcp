# Troubleshooting Guide

This guide covers common issues you might encounter when using SMCP and provides step-by-step solutions.

## 🚨 Quick Diagnosis

### Server Won't Start
```bash
# Check if port is already in use
netstat -an | grep :8000  # Linux/Mac
netstat -an | findstr :8000  # Windows

# Check Python version
python --version

# Check if dependencies are installed
pip list | grep mcp
```

### Connection Issues
```bash
# Test if server is responding
curl http://localhost:8000

# Check firewall settings
# Windows: Check Windows Defender Firewall
# Linux: Check iptables/ufw
# Mac: Check System Preferences > Security & Privacy > Firewall
```

## 🔧 Common Problems & Solutions

### 1. Port Already in Use

**Error Message:**
```
Error: [Errno 98] Address already in use
```

**Solutions:**
```bash
# Option 1: Use a different port
python smcp.py --port 9000

# Option 2: Find and stop the process using port 8000
# Linux/Mac:
lsof -ti:8000 | xargs kill -9

# Windows:
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# Option 3: Wait for port to be released
# (usually happens automatically after a few minutes)
```

### 2. Permission Denied

**Error Message:**
```
Error: [Errno 13] Permission denied
```

**Solutions:**
```bash
# Option 1: Check file permissions
ls -la smcp.py

# Option 2: Make executable
chmod +x smcp.py

# Option 3: Run with appropriate user
sudo python smcp.py  # Not recommended for production

# Option 4: Check directory permissions
ls -la smcp/
```

### 3. Plugin Not Found

**Error Message:**
```
Error: Plugin directory not found: /path/to/plugins
```

**Solutions:**
```bash
# Option 1: Set correct plugin directory
export MCP_PLUGINS_DIR=plugins
python smcp.py

# Option 2: Create plugin directory
mkdir -p plugins

# Option 3: Use absolute path
export MCP_PLUGINS_DIR=/full/path/to/plugins
python smcp.py

# Option 4: Check if plugins directory exists
ls -la plugins/
```

### 4. Network Binding Issues

**Error Message:**
```
Error: [Errno 99] Cannot assign requested address
```

**Solutions:**
```bash
# Option 1: Use localhost-only binding
python smcp.py --host 127.0.0.1

# Option 2: Check network interface
ifconfig  # Linux/Mac
ipconfig  # Windows

# Option 3: Use specific interface
python smcp.py --host 0.0.0.0

# Option 4: Check if interface is up
ip link show
```

### 5. Dependency Issues

**Error Message:**
```
ModuleNotFoundError: No module named 'mcp'
```

**Solutions:**
```bash
# Option 1: Install dependencies
pip install -r requirements.txt

# Option 2: Activate virtual environment
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Option 3: Upgrade pip
pip install --upgrade pip

# Option 4: Install the base MCP library directly
pip install mcp
```

### 6. SSL/TLS Issues

**Error Message:**
```
SSL: CERTIFICATE_VERIFY_FAILED
```

**Solutions:**
```bash
# Option 1: Use HTTP instead of HTTPS for local development
# (SMCP runs on HTTP by default)

# Option 2: If using reverse proxy, check SSL configuration
# This is typically handled by nginx/apache, not SMCP directly

# Option 3: For production, use proper SSL termination
```

### 7. Memory Issues

**Error Message:**
```
MemoryError: Unable to allocate array
```

**Solutions:**
```bash
# Option 1: Check available memory
free -h  # Linux
top       # Mac
Task Manager  # Windows

# Option 2: Reduce plugin load
# Remove unnecessary plugins temporarily

# Option 3: Increase swap space (Linux)
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### 8. Docker Connectivity Issues

**Problem:** Docker containers can't connect to SMCP

**Solutions:**
```bash
# Option 1: Use default binding (0.0.0.0)
python smcp.py  # This is the default

# Option 2: Check Docker network
docker network ls
docker inspect <container_name>

# Option 3: Use host networking
docker run --network host your-container

# Option 4: Check if SMCP is accessible from host
curl http://localhost:8000
```

### 9. Server Exits Immediately with `--allow-external`

**Symptom:** With `--allow-external` (or `MCP_HOST=0.0.0.0`) the process logs a critical error and exits.

**Cause:** SMCP **fails closed** — it refuses to expose an unauthenticated server on a public interface.

**Solutions:**
```bash
# Recommended: set an API key
export MCP_API_KEY="your-long-random-secret"
python smcp.py --allow-external

# Escape hatch (NOT recommended): run open on purpose
MCP_AUTH_DISABLED=1 python smcp.py --allow-external
```

### 10. Clients Get `401 Unauthorized`

**Cause:** The request is missing or presenting the wrong API key on an authenticated transport.

**Solutions:**
- Send the key as `Authorization: Bearer <key>` **or** `X-API-Key: <key>`.
- Confirm the key matches `MCP_API_KEY` / one of `MCP_API_KEYS`.
- Loopback clients skip the key by default; if you set `--require-auth` / `MCP_AUTH_ALLOW_LOOPBACK=0`,
  even local clients must present it.

## 🔍 Advanced Debugging

### Verbose Logging

The rotating file log at `logs/mcp_server.log` already captures `DEBUG`-level detail (the console
shows `INFO` and above). Tail the file for full diagnostics:

```bash
tail -f logs/mcp_server.log
```

> Logging level/destination are currently fixed in code and not yet environment-configurable.

### Network Diagnostics
```bash
# Test local connectivity
telnet localhost 8000

# Test external connectivity (if configured)
telnet your-server-ip 8000

# Check routing
traceroute google.com  # Linux/Mac
tracert google.com     # Windows
```

### Process Monitoring
```bash
# Monitor SMCP process
ps aux | grep mcp_server

# Monitor network connections
netstat -an | grep 8000

# Monitor system resources
htop  # Linux/Mac
top   # Alternative
```

## 📊 Performance Issues

### Slow Response Times
```bash
# Check CPU usage
top -p $(pgrep -f mcp_server)

# Check memory usage
ps -o pid,ppid,cmd,%mem,%cpu --sort=-%mem | head

# Check disk I/O
iostat -x 1  # Linux
```

### High Memory Usage
```bash
# Check memory usage by process
ps aux --sort=-%mem | head

# Check for memory leaks
# Restart server periodically in production
# Monitor memory usage over time
```

## 🚀 Production Issues

### Service Won't Start on Boot
```bash
# Check systemd service (Linux)
sudo systemctl status smcp
sudo systemctl enable smcp

# Check Windows Service
sc query smcp
sc config smcp start=auto

# Check logs
sudo journalctl -u smcp -f
```

### Reverse Proxy Issues
```bash
# Check nginx configuration
sudo nginx -t

# Check nginx logs
sudo tail -f /var/log/nginx/error.log

# Test nginx connectivity
curl -H "Host: your-domain.com" http://localhost
```

## 📞 Getting Help

### Before Asking for Help
1. **Check this guide** for your specific error
2. **Enable debug logging** and check logs
3. **Test with minimal configuration**
4. **Check system resources** (CPU, memory, disk)
5. **Verify network connectivity**

### Information to Provide
When reporting issues, include:
- **Error message** (exact text)
- **SMCP version** (`git rev-parse HEAD`)
- **Python version** (`python --version`)
- **Operating system** and version
- **Steps to reproduce** the issue
- **Logs** with debug level enabled
- **System resources** (CPU, memory, disk)

### Support Channels
- **Website**: [sanctumos.org](https://sanctumos.org)
- **Documentation**: Check the [main documentation](../README.md#-documentation)
- **Issues**: [github.com/sanctumos/smcp/issues](https://github.com/sanctumos/smcp/issues)

---

**Still having issues?** Check the [Getting Started Guide](getting-started.md) for basic setup, or report the problem with detailed information on GitHub Issues.
