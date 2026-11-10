package com.example.pleosprojectv01

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ConvoyApiTest {
    @Test
    fun httpsAddressIsTrimmed() {
        assertEquals("https://example.com:8765", ConvoyApi.validateServer(" https://example.com:8765/ "))
    }

    @Test
    fun debugAllowsOnlyLocalHttpHosts() {
        for (host in listOf("localhost", "127.0.0.1", "10.0.2.2")) {
            assertEquals("http://$host:8765", ConvoyApi.validateServer("http://$host:8765"))
        }
        for (host in listOf("example.com", "192.168.0.1", "10.0.2.2.evil.example")) {
            assertThrows(IllegalArgumentException::class.java) { ConvoyApi.validateServer("http://$host") }
        }
    }

    @Test
    fun embeddedCredentialsPathsAndQueriesAreRejected() {
        for (url in listOf("https://user:pass@example.com", "https://example.com/api",
            "https://example.com?token=secret", "https://example.com#fragment")) {
            assertThrows(IllegalArgumentException::class.java) { ConvoyApi.validateServer(url) }
        }
    }

    @Test
    fun missingHostAndUnsupportedSchemesAreRejected() {
        for (url in listOf("localhost:8765", "file:///tmp", "ftp://example.com")) {
            assertThrows(IllegalArgumentException::class.java) { ConvoyApi.validateServer(url) }
        }
        assertThrows(java.net.URISyntaxException::class.java) { ConvoyApi.validateServer("https:///") }
    }
}
