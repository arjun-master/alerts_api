package com.chartink.webhook;

import com.tts.in.model.FyersClass;
import org.json.JSONObject;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;

public class FyersAuthTest {
    private static final String APP_ID = "RWCTF2HW7T-100";
    private static final String SECRET_ID = "Y5BBJF9DW9";
    private static final String REDIRECT_URI = "https://trade.fyers.in/api-login/redirect-uri/index.html";

    @Test
    public void testFyersAuth() throws Exception {
        // 1. Generate app ID hash
        String appIdHash = generateAppIdHash();
        System.out.println("App ID Hash: " + appIdHash);

        // 2. Get Fyers instance
        FyersClass fyersClass = FyersClass.getInstance();

        // 3. Generate auth code URL
        String state = generateState();
        String authUrl = String.format(
            "https://api.fyers.in/api/v3/generate-authcode?" +
            "client_id=%s&redirect_uri=%s&response_type=code&state=%s",
            APP_ID, REDIRECT_URI, state
        );
        System.out.println("\nAuth URL (open this in browser):\n" + authUrl);

        // 4. After getting auth code from redirect URL, use it here
        System.out.println("\nAfter logging in, you'll get redirected to the redirect URI.");
        System.out.println("Copy the 'auth_code' parameter from the URL and use it to generate the token:");
        System.out.println("fyersClass.GenerateToken(\"YOUR_AUTH_CODE\", \"" + appIdHash + "\");");
    }

    private String generateAppIdHash() throws Exception {
        String data = APP_ID + ":" + SECRET_ID;
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] hash = digest.digest(data.getBytes(StandardCharsets.UTF_8));
        return Base64.getEncoder().withoutPadding().encodeToString(hash);
    }

    private String generateState() throws Exception {
        String stateData = APP_ID + ":" + REDIRECT_URI;
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] hash = digest.digest(stateData.getBytes(StandardCharsets.UTF_8));
        return Base64.getUrlEncoder().withoutPadding().encodeToString(hash);
    }
} 