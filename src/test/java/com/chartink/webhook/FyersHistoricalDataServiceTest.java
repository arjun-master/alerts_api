package com.chartink.webhook;

import com.chartink.webhook.service.FyersHistoricalDataService;
import org.json.JSONObject;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.time.LocalDate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

@SpringBootTest
public class FyersHistoricalDataServiceTest {

    @Autowired
    private FyersHistoricalDataService historicalDataService;

    @Test
    public void testGetHistoricalData() throws Exception {
        // Get historical data for SBIN for February 2024
        JSONObject result = historicalDataService.getHistoricalData(
            "NSE:SBIN-EQ",
            "D",  // Daily resolution
            LocalDate.of(2024, 2, 1),
            LocalDate.of(2024, 2, 29)
        );

        System.out.println("Historical Data Response: " + result.toString(2));
        
        assertNotNull(result);
        assertEquals("ok", result.getString("s"));
    }
} 