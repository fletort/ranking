# Install Ranking POC on a VM

## As a systemd oneshot service

### Create configuration file

```bash
sudo mkdir -p /etc/ranking
```

### Install service definition

```bash
sudo cp deployment/systemd/ranking.list.example \
   /etc/systemd/system/ranking.list.service
```

### Install environment configuration

```bash
sudo cp deployment/examples/ranking.env.example \
   /etc/ranking/ranking.env
```

### Customize the installation

Edit the service definition:

```bash
sudo vi /etc/systemd/system/ranking.list.service
```

Update:

- `WorkingDirectory`
- `ExecStart`

Edit the environment configuration:

```bash
sudo vi /etc/ranking/ranking.env
```

Update:

- storage backend
- bucket name
- credentials
- logging configuration

### Reload systemd configuration

```bash
sudo systemctl daemon-reload
```

### Run the crawler

```bash
sudo systemctl start --no-block ranking.list
```

### Check execution status

```bash
sudo systemctl status ranking.list
```

### View logs

```bash
journalctl -u ranking.list
```

Follow logs in real time:

```bash
journalctl -u ranking.list -f
```
