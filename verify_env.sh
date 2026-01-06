#!/bin/bash
echo "🔐 ENCRYPTION & .env COMPLETE VERIFICATION"
echo "=========================================="

# Check .env exists
if [ ! -f .env ]; then
    echo "❌ CRITICAL: .env file missing"
    echo "Creating template..."
    cat > .env << 'TEMPLATE'
BOT_TOKEN=7960003520:AAERf6LxK0aQH7rbkLKjikBBM1UrypNZBBM
ADMIN_ID=6920399284
SECRET_CODE=2008
SECRET_CODE_EXPIRY=2024-12-31
ENCRYPTION_KEY=gAAAAABlxiXJ3Mx5Y6z8NcDvFgHjK1MnPqRsTuVwYzA2C4E6G8I0K2M4O6Q8S0U2W4Y6A8C0E2G4I6K8M0O2Q4S6U8W0Y2A4C6E8G0I2K4M6O8Q0S2U4W6Y8==
PORT=8000
TEMPLATE
    echo "✅ Template .env created"
fi

# Read .env
echo ""
echo "📄 .env FILE:"
echo "------------"
cat .env

echo ""
echo "🔍 DETAILED ANALYSIS:"
echo "-------------------"

# Extract all variables
while IFS='=' read -r key value; do
    [[ $key =~ ^#.* ]] || [[ -z $key ]] && continue
    
    # Mask sensitive values
    if [[ $key == "BOT_TOKEN" || $key == "ENCRYPTION_KEY" ]]; then
        masked="${value:0:10}...${value: -5}"
        printf "%-20s = %s\n" "$key" "$masked"
    else
        printf "%-20s = %s\n" "$key" "$value"
    fi
done < .env

# Encryption key specific check
echo ""
echo "🔐 ENCRYPTION KEY ANALYSIS:"
KEY=$(grep ENCRYPTION_KEY .env | cut -d= -f2)

if [ -n "$KEY" ]; then
    echo "✅ Key present"
    echo "Length: ${#KEY} chars"
    
    # Check format
    if [[ $KEY == gAAAAA* ]]; then
        echo "✅ Starts with 'gAAAAA' (correct)"
    else
        echo "❌ Should start with 'gAAAAA'"
    fi
    
    # Check ending
    if [[ $KEY == *=* ]]; then
        echo "✅ Contains '=' padding"
    fi
    
    # Count = signs
    equals=$(echo "$KEY" | tr -cd '=' | wc -c)
    echo "Padding '=' count: $equals"
    
    # Test if it's valid base64 (simplified)
    if echo "$KEY" | grep -q '^[A-Za-z0-9+/]*=*$'; then
        echo "✅ Valid Base64 characters"
    else
        echo "❌ Invalid characters detected"
    fi
else
    echo "❌ ENCRYPTION_KEY not found"
fi

echo ""
echo "🎯 VERIFICATION SCORE:"
count=0
total=5

[ -f .env ] && ((count++))
[ -n "$(grep BOT_TOKEN .env)" ] && ((count++))
[ -n "$(grep ADMIN_ID .env)" ] && ((count++))
[ -n "$(grep ENCRYPTION_KEY .env)" ] && ((count++))
[ -n "$(grep SECRET_CODE .env)" ] && ((count++))

echo "$count/$total tests passed"
if [ $count -eq $total ]; then
    echo "✅ READY FOR RAILWAY!"
else
    echo "⚠️  Needs attention"
fi
