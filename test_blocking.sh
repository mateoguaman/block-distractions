#!/bin/bash
# Test script to verify blocking for all sites in /etc/hosts

echo "========================================"
echo "Block Distractions - Blocking Test"
echo "========================================"
echo ""

# Extract blocked sites from hosts file
SITES=$(grep -E "^127\.0\.0\.1 " /etc/hosts | grep -v localhost | grep -v "www\." | awk '{print $2}')

if [ -z "$SITES" ]; then
    echo "No blocked sites found in /etc/hosts"
    exit 1
fi

echo "Testing $(echo "$SITES" | wc -l | tr -d ' ') blocked sites..."
echo ""

PASSED=0
FAILED=0
FAILED_SITES=""

for site in $SITES; do
    # Test IPv4 resolution
    IPV4=$(dig +short A "$site" 2>/dev/null | head -1)

    # Test IPv6 resolution
    IPV6=$(dig +short AAAA "$site" 2>/dev/null | head -1)

    # Check system resolver (what apps actually use)
    PING_IP=$(ping -c 1 -t 1 "$site" 2>/dev/null | head -1 | grep -oE '\(([0-9]+\.){3}[0-9]+\)' | tr -d '()')

    # Determine status
    STATUS="?"
    REASON=""

    if [ "$PING_IP" = "127.0.0.1" ]; then
        # System resolver returns localhost - blocked!
        if [ -n "$IPV6" ] && [ "$IPV6" != "::1" ]; then
            # Has external IPv6 - check if hosts file has ::1 entry
            if grep -q "::1 $site" /etc/hosts 2>/dev/null; then
                STATUS="OK"
                REASON="IPv4+IPv6 blocked"
            else
                STATUS="WARN"
                REASON="Missing ::1 entry (has external IPv6: $IPV6)"
            fi
        else
            STATUS="OK"
            REASON="Blocked (no external IPv6)"
        fi
    else
        STATUS="FAIL"
        if [ -n "$PING_IP" ]; then
            REASON="Resolves to $PING_IP instead of 127.0.0.1"
        else
            REASON="Could not resolve"
        fi
    fi

    # Print result
    if [ "$STATUS" = "OK" ]; then
        echo "✅ $site - $REASON"
        ((PASSED++))
    elif [ "$STATUS" = "WARN" ]; then
        echo "⚠️  $site - $REASON"
        ((PASSED++))
    else
        echo "❌ $site - $REASON"
        ((FAILED++))
        FAILED_SITES="$FAILED_SITES $site"
    fi
done

echo ""
echo "========================================"
echo "Results: $PASSED passed, $FAILED failed"
echo "========================================"

if [ $FAILED -gt 0 ]; then
    echo ""
    echo "Failed sites:$FAILED_SITES"
    echo ""
    echo "Try running: sudo killall -9 mDNSResponder"
fi
