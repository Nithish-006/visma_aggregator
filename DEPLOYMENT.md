# 🚀 VISMA Financial App - Production Deployment Guide

This guide covers deploying your VISMA Financial App to production using **FREE** hosting services.

## 📋 Table of Contents

1. [Recommended Free Hosting Options](#recommended-free-hosting-options)
2. [Quick Start - Railway (Easiest)](#option-1-railway-easiest)
3. [Alternative - Render](#option-2-render)
4. [Database Setup](#database-setup)
5. [Environment Variables](#environment-variables)
6. [Post-Deployment Steps](#post-deployment-steps)
7. [Troubleshooting](#troubleshooting)

---

## 🎯 Recommended Free Hosting Options

### **Best Options (App + Database Combined):**

| Service | Free Tier | Database | Best For |
|---------|-----------|----------|----------|
| **Railway** ✅ | $5/month credit (500hrs) | MySQL included | Easiest setup |
| **Render** ✅ | 750hrs/month | PostgreSQL free | Reliable, simple |
| **PythonAnywhere** | 1 app free | MySQL included | Python-focused |

### **Separate Database Hosting:**

| Service | Free Tier | Notes |
|---------|-----------|-------|
| **PlanetScale** ✅ | 5GB storage | MySQL-compatible |
| **Aiven** | 1 service free | 30-day trial |
| **Railway** | Included with app | Recommended |

---

## 🚂 Option 1: Railway (Easiest) ⭐ RECOMMENDED

Railway provides the simplest deployment with app + MySQL database included.

### Step 1: Prepare Your Code

1. **Add `.gitignore`** (if not already present):
```
__pycache__/
*.pyc
.env
uploads/
*.xlsx
*.xls
venv/
```

2. **Create `Procfile`** in your project root:
```
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

3. **Install production dependencies**:
```bash
pip install -r requirements-production.txt
```

### Step 2: Deploy to Railway

1. **Sign up**: Go to [railway.app](https://railway.app) and sign up with GitHub
2. **Create New Project**: Click "New Project"
3. **Select "Deploy from GitHub repo"**: Connect your repository
4. **Add MySQL Database**:
   - In your project, click "+ New"
   - Select "Database" → "MySQL"
   - Railway will create a MySQL instance

5. **Set Environment Variables**:
   - Click on your app service
   - Go to "Variables" tab
   - Add these variables:

```env
SECRET_KEY=your-random-secret-key-here-generate-new-one
DB_HOST=${{MySQL.MYSQL_URL}}
DB_DATABASE=visma_financial
DB_USER=${{MySQL.MYSQLUSER}}
DB_PASSWORD=${{MySQL.MYSQLPASSWORD}}
DB_PORT=3306
FLASK_ENV=production
DEBUG=False
```

6. **Initialize Database**:
   - Connect to your MySQL instance using Railway's web terminal or MySQL client
   - Run your `database_schema.sql` file:
```bash
# Download Railway CLI
npm install -g @railway/cli

# Login
railway login

# Connect to MySQL
railway connect MySQL

# Then run:
source database_schema.sql
```

### Step 3: Deploy

Railway will automatically deploy when you push to your GitHub repository!

**Your app will be live at**: `https://your-app-name.up.railway.app`

---

## 🎨 Option 2: Render

Render offers 750 hours/month free (sufficient for one app running 24/7).

### Step 1: Prepare Code

Same as Railway - add `Procfile` and `.gitignore`

### Step 2: Create Database

1. **Sign up**: Go to [render.com](https://render.com)
2. **Create PostgreSQL Database**:
   - Click "New +" → "PostgreSQL"
   - Name: `visma-financial-db`
   - Select free tier
   - Click "Create Database"
   - **Note**: Render uses PostgreSQL, not MySQL. You'll need to:
     - Install `psycopg2-binary` instead of `mysql-connector-python`
     - Update database code to use PostgreSQL syntax

**OR use external MySQL:**
- Use PlanetScale (free MySQL)
- Get connection details and add to Render environment variables

### Step 3: Deploy App

1. **Create Web Service**:
   - Click "New +" → "Web Service"
   - Connect your GitHub repository
   - Settings:
     - **Name**: `visma-financial-app`
     - **Environment**: Python 3
     - **Build Command**: `pip install -r requirements-production.txt`
     - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT`

2. **Add Environment Variables**:
```env
SECRET_KEY=your-secret-key
DB_HOST=your-mysql-host
DB_DATABASE=visma_financial
DB_USER=your-db-user
DB_PASSWORD=your-db-password
DB_PORT=3306
PYTHON_VERSION=3.11.0
```

3. **Deploy**: Click "Create Web Service"

**Your app will be live at**: `https://visma-financial-app.onrender.com`

---

## 🐍 Option 3: PythonAnywhere

PythonAnywhere is Python-focused and includes MySQL.

### Steps:

1. **Sign up**: [pythonanywhere.com](https://www.pythonanywhere.com)
2. **Upload Code**: Use Git or web interface
3. **Create MySQL Database**: In "Databases" tab
4. **Create Web App**:
   - Go to "Web" tab
   - "Add a new web app"
   - Choose Flask
   - Point to your `app.py`
5. **Configure WSGI**: Edit `/var/www/yourusername_pythonanywhere_com_wsgi.py`
6. **Add Environment Variables**: In `.env` file or web app settings

**Your app will be live at**: `https://yourusername.pythonanywhere.com`

---

## 💾 Database Setup

### Initialize Your Production Database

**Method 1: Direct MySQL Connection**

```bash
mysql -h YOUR_HOST -u YOUR_USER -p YOUR_DATABASE < database_schema.sql
```

**Method 2: Via Python Script**

Create `init_db.py`:

```python
import mysql.connector
from config import Config

conn = mysql.connector.connect(
    host=Config.DB_HOST,
    user=Config.DB_USER,
    password=Config.DB_PASSWORD,
    port=Config.DB_PORT
)

cursor = conn.cursor()

# Read and execute schema
with open('database_schema.sql', 'r') as f:
    sql = f.read()
    for statement in sql.split(';'):
        if statement.strip():
            cursor.execute(statement)

conn.commit()
print("Database initialized successfully!")
```

Run: `python init_db.py`

---

## 🔐 Environment Variables

### Generate Secure SECRET_KEY

```python
import secrets
print(secrets.token_hex(32))
```

### Required Environment Variables

Create a `.env` file (copy from `.env.example`):

```env
# PRODUCTION SETTINGS
SECRET_KEY=<generate-random-64-char-string>
FLASK_ENV=production
DEBUG=False

# DATABASE
DB_HOST=<your-mysql-host>
DB_DATABASE=visma_financial
DB_USER=<your-db-username>
DB_PASSWORD=<your-db-password>
DB_PORT=3306

# UPLOAD
UPLOAD_FOLDER=uploads
MAX_CONTENT_LENGTH=16777216
```

**⚠️ NEVER commit `.env` to Git!**

---

## ✅ Post-Deployment Steps

### 1. Test Your Deployment

- Visit your app URL
- Test upload functionality
- Test transaction editing
- Check database connectivity

### 2. Monitor Your App

- **Railway**: Built-in metrics and logs
- **Render**: Logs tab in dashboard
- **PythonAnywhere**: Error logs and server logs

### 3. Set Up SSL (HTTPS)

All mentioned platforms provide **free SSL certificates automatically**!

### 4. Custom Domain (Optional)

- Railway: $5/month for custom domain
- Render: Free custom domain support
- PythonAnywhere: Custom domains on paid plans

---

## 🐛 Troubleshooting

### "Application Error" on startup

**Check logs**:
- Railway: Click "Deployments" → View logs
- Render: Click "Logs" tab
- Look for Python errors

**Common fixes**:
```bash
# Ensure gunicorn is installed
pip install gunicorn

# Check Procfile exists
cat Procfile

# Verify environment variables are set
```

### Database Connection Issues

```python
# Test database connection
python -c "from database import test_connection; test_connection()"
```

**Common issues**:
- Wrong DB_HOST (check if using internal or external host)
- Firewall blocking connection
- Wrong credentials

### Upload Folder Missing

```python
# Add to app.py
import os
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
```

### Port Already in Use

Gunicorn automatically uses `$PORT` environment variable. Ensure:
```
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

---

## 📊 Cost Breakdown (Free Tier)

| Service | Monthly Cost | Limitations |
|---------|--------------|-------------|
| **Railway** | $0 ($5 credit/mo) | ~500 hours runtime |
| **Render** | $0 | 750 hours/month |
| **PythonAnywhere** | $0 | 1 app, limited CPU |
| **PlanetScale** | $0 | 5GB storage, 1 billion reads |

**Recommendation**: Start with **Railway** for simplest setup. It's perfect for personal/small business use.

---

## 🎓 Next Steps

1. ✅ Choose your hosting platform
2. ✅ Set up your database
3. ✅ Configure environment variables
4. ✅ Deploy your app
5. ✅ Test thoroughly
6. ✅ Set up regular backups (database exports)

---

## 📞 Need Help?

- **Railway Discord**: Great community support
- **Render Community**: Forums and documentation
- **Stack Overflow**: Tag questions with `flask` and `mysql`

---

**🎉 Congratulations! Your VISMA Financial App is now in production!**

