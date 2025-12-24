# 🚀 Quick Start Deployment Guide

Get your VISMA Financial App live in **15 minutes** using Railway (FREE)!

## ✅ Prerequisites

- Git installed
- GitHub account
- Your code pushed to GitHub repository

## 🚂 Deploy to Railway (Recommended - FREE)

### Step 1: Install Dependencies Locally (Test First)

```bash
# Install production requirements
pip install -r requirements.txt

# Test locally
python app.py
```

### Step 2: Set Up Railway

1. **Sign up**: Visit [railway.app](https://railway.app)
   - Click "Login with GitHub"
   - Authorize Railway

2. **Create New Project**:
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your `VISMA-AGGREGATOR` repository
   - Click "Deploy Now"

### Step 3: Add MySQL Database

1. In your Railway project dashboard:
   - Click "+ New"
   - Select "Database"
   - Click "Add MySQL"
   - Railway will provision a MySQL database

### Step 4: Configure Environment Variables

1. Click on your **app service** (not the MySQL service)
2. Go to "Variables" tab
3. Click "+ New Variable" and add these:

```
SECRET_KEY = <generate using: python -c "import secrets; print(secrets.token_hex(32))">
FLASK_ENV = production
DEBUG = False
DB_HOST = ${{MySQL.MYSQLHOST}}
DB_DATABASE = visma_financial
DB_USER = ${{MySQL.MYSQLUSER}}
DB_PASSWORD = ${{MySQL.MYSQLPASSWORD}}
DB_PORT = ${{MySQL.MYSQLPORT}}
UPLOAD_FOLDER = uploads
```

**💡 Tip**: Railway automatically provides `${{MySQL.*}}` variables from your MySQL service!

### Step 5: Initialize Database

**Option A: Using Railway CLI (Recommended)**

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Link to your project
railway link

# Connect to MySQL
railway connect MySQL

# Once connected, run:
mysql> source database_schema.sql;
mysql> exit;
```

**Option B: Using MySQL Workbench or Any MySQL Client**

1. Get connection details from Railway MySQL service:
   - Click on MySQL service → "Connect" tab
   - Copy host, port, username, password

2. Connect using MySQL Workbench:
   - Create new connection
   - Paste the details
   - Run `database_schema.sql` file

### Step 6: Deploy!

Railway will automatically deploy when you:
- Push to your GitHub repository
- Or click "Deploy" in Railway dashboard

**🎉 Your app is now live!**

Find your URL in Railway dashboard (looks like: `https://your-app.up.railway.app`)

---

## 🔍 Verify Deployment

1. **Visit your app URL**
2. **Test upload**: Try uploading a bank statement
3. **Test editing**: Navigate to `/edit-transactions`
4. **Check database**: Verify transactions are saved

---

## 📊 Monitor Your App

Railway provides:
- ✅ **Logs**: Real-time application logs
- ✅ **Metrics**: CPU, Memory, Network usage
- ✅ **Deployments**: History of all deployments

Access via Railway dashboard → Click your service → "Observability"

---

## 💰 Free Tier Limits

Railway Free Tier:
- **$5 credit per month**
- **~500 hours runtime** (about 20 days 24/7)
- **100GB bandwidth**
- **1GB storage** (database)

**Perfect for personal/small business use!**

---

## 🐛 Common Issues & Fixes

### "Application Error" after deployment

**Check logs**:
```bash
railway logs
```

**Common fixes**:
1. Ensure `Procfile` exists and is correct
2. Verify all environment variables are set
3. Check database connection string

### Database connection fails

**Verify variables**:
```bash
railway variables
```

Make sure MySQL variables are properly linked: `${{MySQL.MYSQLHOST}}`

### Upload folder missing

Already handled in `app.py` with:
```python
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
```

---

## 🎓 Next Steps

1. ✅ Set up **automatic backups** of your database
2. ✅ Add **custom domain** (optional, $5/month on Railway)
3. ✅ Set up **monitoring** alerts
4. ✅ Review **security settings**

---

## 🆘 Need Help?

- **Railway Discord**: https://discord.gg/railway
- **Documentation**: https://docs.railway.app
- **Your app logs**: `railway logs` or check dashboard

---

**Congratulations! Your VISMA Financial App is in production! 🎉**
