package com.chartink.webhook.model;

import lombok.Data;
import com.fasterxml.jackson.annotation.JsonProperty;

@Data
public class ChartinkAlert {
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