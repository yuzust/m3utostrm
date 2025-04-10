# M3U to STRM Converter

A powerful web application that converts M3U playlists into STRM files for seamless integration with media centers like Emby and Jellyfin.

## ✨ Features

- 🔄 **Process M3U files** from URLs or local uploads
- 📊 **Intelligent content detection** to categorize Movies and TV Shows
- 📝 **Metadata extraction** including resolution, year, season, and episode information
- ⏱️ **Scheduled updates** to keep your content library fresh
- 📊 **Content statistics** and processing history
- 🔔 **Real-time notifications** via browser and Discord webhooks
- 📁 **Organized directory structure** for media centers

## 🚀 Installation

### Requirements

- Python 3.7+
- pip (Python package manager)

### Quick Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/m3u-to-strm-converter.git
cd m3u-to-strm-converter
```

2. Create a virtual environment (optional but recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run the application:
```bash
python app.py
```

The application will be available at http://localhost:8768 by default.

### Docker Installation

```dockerfile
services:
  m3u-converter:
    image: m3utostrm
    container_name: m3u-converter
    ports:
      - "8768:8768"
    volumes:
      - /mnt/m3utostrm/data:/app/data
      - /mnt/m3utostrm/logs:/app/logs
      - /mnt/m3utostrm/content:/app/content
      - /mnt/m3utostrm/uploads:/app/uploads
    restart: unless-stopped
    environment:
      - TZ=UTC  # Set your preferred timezone
```

```bash
docker pull ghcr.io/yuzust/m3utostrm:latest
```

## 🖥️ Usage

1. **Access the web interface** at http://localhost:8768
2. **Upload an M3U file** or **provide an M3U URL**
3. **Configure output options** if needed
4. **Start processing** to create STRM files
5. **Schedule regular updates** if desired

Your STRM files will be organized in the content directory like this:
```
content/
├── Movies/
│   ├── Movie Title 1/
│   │   └── Movie Title 1 - 1080p.strm
│   └── Movie Title 2/
│       └── Movie Title 2 - 720p.strm
└── TV Shows/
    ├── Show Title 1/
    │   ├── Season 01/
    │   │   ├── Show Title 1 - S01E01 - Episode Title.strm
    │   │   └── Show Title 1 - S01E02 - Episode Title.strm
    │   └── Season 02/
    │       └── Show Title 1 - S02E01 - Episode Title.strm
    └── Show Title 2/
        └── Season 01/
            └── Show Title 2 - S01E01 - Episode Title.strm
```

## ⚙️ Configuration

The application can be configured by editing `config.py` or through the web interface. Key configuration options include:

- **Output path**: Where STRM files are created
- **Content keywords**: To help identify movies vs TV shows
- **Language filter**: Filter content by language
- **Update frequency**: How often to check for M3U updates
- **Notification settings**: Enable/disable and configure Discord webhooks

## 🚀 Advanced Features

### M3U Proxy

The M3U proxy feature allows you to:
- Create optimized versions of M3U playlists
- Filter channels by group or name
- Remove VOD content
- Fix channel names
- Renumber channels

### API

The application provides a comprehensive REST API for automation:

- `/api/m3u` - M3U file upload and processing
- `/api/content` - Content browsing and management
- `/api/proxy` - M3U proxy management
- `/api/config` - Application configuration
- `/api/status` - System status and monitoring

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 📬 Contact

If you have any questions or suggestions, please open an issue on GitHub.
