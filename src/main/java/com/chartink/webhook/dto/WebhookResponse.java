package com.chartink.webhook.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Data;

import java.util.Map;

@Data
@Builder
public class WebhookResponse {
    private String message;
    private boolean success;
    
    @JsonProperty("scan_name")
    private String scanName;
    
    @JsonProperty("alert_name")
    private String alertName;
    
    @JsonProperty("stock_analysis")
    private Map<String, StockAnalysis> stockAnalysis;
    
    @JsonProperty("triggered_at")
    private String triggeredAt;

    @Data
    @Builder
    public static class StockAnalysis {
        @JsonProperty("trigger_price")
        private String triggerPrice;
        
        @JsonProperty("returns")
        private Returns returns;
    }

    @Data
    @Builder
    public static class Returns {
        @JsonProperty("one_day")
        private double oneDay;
        
        @JsonProperty("three_day")
        private double threeDay;
        
        @JsonProperty("one_week")
        private double oneWeek;
    }
} 