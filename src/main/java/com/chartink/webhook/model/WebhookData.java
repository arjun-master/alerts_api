package com.chartink.webhook.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class WebhookData {
    @JsonProperty("alert_name")
    private String alertName;
    
    @JsonProperty("scan_name")
    private String scanName;
    
    private String stocks;
    
    @JsonProperty("trigger_prices")
    private String triggerPrices;
    
    @JsonProperty("triggered_at")
    private String triggeredAt;
} 