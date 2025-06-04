package com.chartink.webhook;

import com.chartink.webhook.service.FyersTokenGenerator;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.junit.jupiter.api.Assertions.assertNotNull;

@SpringBootTest
public class FyersTokenGeneratorTest {

    @Autowired
    private FyersTokenGenerator fyersTokenGenerator;

    @Test
    public void testTokenGeneration() throws Exception {
        String token = fyersTokenGenerator.getToken();
        assertNotNull(token);
        System.out.println("Generated Token: " + token);
    }
} 