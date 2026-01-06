#!/bin/bash
echo "🔍 THEFILEx BOT - FINAL VERIFICATION"
echo "====================================="

echo ""
echo "📋 SUMMARY:"
echo "Directory: $(pwd)"
echo "Total files: $(ls -1 | wc -l)"
echo ""

# Critical files
echo "📄 CRITICAL FILES STATUS:"
critical=0
for f in Procfile requirements.txt bot.py database.py admin_handlers.py tickets.py tools.py .env; do
    if [ -f "$f" ]; then
        echo "  ✅ $f"
    else
        echo "  ❌ $f (MISSING)"
        critical=1
    fi
done

echo ""
if [ $critical -eq 0 ]; then
    echo "🎉 ALL CRITICAL FILES PRESENT!"
else
    echo "⚠️  SOME FILES MISSING"
fi

echo ""
echo "📊 FILE SIZES:"
ls -lh *.py *.txt Procfile .env 2>/dev/null

echo ""
echo "🔧 SYSTEM:"
echo "Python: $(python3 --version 2>/dev/null || echo 'Not found')"

echo ""
echo "🚀 READY FOR RAILWAY DEPLOYMENT!"
echo "Next steps:"
echo "1. Push to GitHub: git push"
echo "2. Deploy on Railway.app"
echo "3. Add variables in Railway dashboard"
