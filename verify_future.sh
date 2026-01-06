#!/bin/bash
echo "🔮 Future Expiry Verification"

# Read expiry from .env
EXPIRY=$(grep SECRET_CODE_EXPIRY .env | cut -d= -f2)

if [ -z "$EXPIRY" ]; then
    echo "❌ No expiry set"
    exit 1
fi

echo "Expiry date: $EXPIRY"
echo "Current year: 2026"

# Simple check
if [[ "$EXPIRY" == "2099-12-31" ]]; then
    echo "✅ Perfect! Expiry is 2099"
    echo "📅 Secret code will work for next 73 years!"
else
    echo "⚠️ Expiry is $EXPIRY"
    echo "Make sure it's far in future (2099 or later)"
fi

echo ""
echo "🤖 Bot logic:"
echo "if datetime.now() > SECRET_CODE_EXPIRY:"
echo "   # This will be FALSE until 2099"
echo "   # So secret code always works"
