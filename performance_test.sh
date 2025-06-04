#!/bin/bash

echo "Starting performance test - will run for 5 minutes..."
echo "Start time: $(date)"

# Counter for successful and failed requests
success_count=0
fail_count=0
total_time=0
rate_limit_errors=0

# Function to generate random stock data
generate_stock_data() {
    local stocks=("RELIANCE" "TCS" "HDFCBANK" "INFY" "ICICIBANK" "WIPRO" "SBIN" "TATASTEEL" "AXISBANK" "SUNPHARMA")
    local prices=("2500.50" "3890.25" "1520.75" "1560.80" "1020.35" "450.60" "750.90" "145.80" "1105.60" "1280.35")
    
    # Randomly select 3-5 stocks
    local num_stocks=$((RANDOM % 3 + 3))
    local selected_stocks=""
    local selected_prices=""
    
    for ((i=0; i<num_stocks; i++)); do
        local idx=$((RANDOM % ${#stocks[@]}))
        if [ -z "$selected_stocks" ]; then
            selected_stocks="${stocks[$idx]}"
            selected_prices="${prices[$idx]}"
        else
            selected_stocks="$selected_stocks, ${stocks[$idx]}"
            selected_prices="$selected_prices, ${prices[$idx]}"
        fi
    done
    
    echo "{\"alert_name\": \"Performance Test Alert\", \"scan_name\": \"Load Test Scan $((RANDOM % 100))\", \"stocks\": \"$selected_stocks\", \"trigger_prices\": \"$selected_prices\", \"triggered_at\": \"$(date +"%Y-%m-%d %H:%M:%S")\"}"
}

# Function to send a single request
send_request() {
    local start_time=$(date +%s%N)
    
    local response=$(curl -s -w "\n%{http_code}" -X POST http://localhost:8080/api/webhook \
        -H "Content-Type: application/json" \
        -d "$(generate_stock_data)")
    
    local end_time=$(date +%s%N)
    local duration=$(( (end_time - start_time) / 1000000 )) # Convert to milliseconds
    
    local http_code=$(echo "$response" | tail -n1)
    local response_body=$(echo "$response" | head -n1)
    
    echo "$http_code:$duration:$response_body"
}

# Run for 5 minutes (300 seconds)
end=$((SECONDS + 300))

# Number of concurrent requests (reduced to match rate limit)
CONCURRENCY=3
BATCH_INTERVAL=0.2  # 200ms between batches

# Create a temporary file for storing results
RESULTS_FILE=$(mktemp)

# Function to handle rate limit backoff
handle_rate_limit() {
    local backoff_time=$1
    echo "Rate limit hit, backing off for ${backoff_time} seconds..."
    sleep "$backoff_time"
}

# Initialize backoff time
backoff_time=1

while [ $SECONDS -lt $end ]; do
    # Launch concurrent requests
    for ((i=1; i<=CONCURRENCY; i++)); do
        send_request >> "$RESULTS_FILE" &
    done
    
    # Wait for all background processes to complete
    wait
    
    # Check for rate limit errors in the most recent batch
    recent_rate_limits=$(tail -n "$CONCURRENCY" "$RESULTS_FILE" | grep -c "429")
    
    if [ "$recent_rate_limits" -gt 0 ]; then
        ((rate_limit_errors+=recent_rate_limits))
        handle_rate_limit "$backoff_time"
        backoff_time=$((backoff_time * 2))  # Exponential backoff
        [ "$backoff_time" -gt 8 ] && backoff_time=8  # Cap at 8 seconds
    else
        backoff_time=1  # Reset backoff time if no rate limits
        sleep "$BATCH_INTERVAL"  # Normal interval between batches
    fi
done

# Process results
while IFS=: read -r http_code duration response_body; do
    if [ "$http_code" == "200" ]; then
        ((success_count++))
    else
        ((fail_count++))
        echo "Failed request: HTTP $http_code - $response_body"
    fi
    total_time=$((total_time + duration))
done < "$RESULTS_FILE"

# Calculate and display statistics
total_requests=$((success_count + fail_count))
avg_time=$(echo "scale=2; $total_time / $total_requests" | bc)
requests_per_second=$(echo "scale=2; $total_requests / 300" | bc)

echo
echo "Performance Test Results"
echo "======================="
echo "Total Requests: $total_requests"
echo "Successful Requests: $success_count"
echo "Failed Requests: $fail_count"
echo "Rate Limit Errors: $rate_limit_errors"
echo "Average Response Time: ${avg_time}ms"
echo "Requests per Second: $requests_per_second"
echo "Success Rate: $(echo "scale=2; ($success_count * 100) / $total_requests" | bc)%"
echo "End time: $(date)"

# Cleanup
rm -f "$RESULTS_FILE" 