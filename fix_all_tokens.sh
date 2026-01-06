#!/bin/bash
echo "🔧 Fixing wrong bot token in all files..."

WRONG_TOKEN="7960003520:AAERf6LxK0aQH7rbkLKjikBBM1UrypNZBBM"
CORRECT_TOKEN="7960003520:AAERf6LxK0aQH7rbkLKjikBBM1UrypNZBBM"

echo "Wrong: $WRONG_TOKEN"
echo "Correct: $CORRECT_TOKEN"
echo ""

# Find all files with wrong token
echo "📁 Files with wrong token:"
grep -l "$WRONG_TOKEN" ./* 2>/dev/null

# Replace in all files
echo ""
echo "🔄 Replacing in all files..."
find . -type f -name "*.py" -o -name "*.txt" -o -name ".env" | while read file; do
    if grep -q "$WRONG_TOKEN" "$file" 2>/dev/null; then
        sed -i "s|$WRONG_TOKEN|$CORRECT_TOKEN|g" "$file"
        echo "✅ Fixed: $file"
    fi
done

echo ""
echo "✅ All files updated with correct token!"
