package com.example.pleosprojectv01

import android.os.Bundle
import ai.pleos.playground.navi.data.CurrentLocationInfo
import ai.pleos.playground.navi.helper.NaviHelper
import ai.pleos.playground.navi.helper.listener.NaviHelperEventListener
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Read-only SDK query; opt in with `-e probe true`. Does not request a route. */
@RunWith(AndroidJUnit4::class)
class NavigationLocationProbeTest {
    @Test
    fun queryNavigationCurrentPosition() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("probe") == "true")
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val connected = CountDownLatch(1)
        val received = CountDownLatch(1)
        var connectionFailure: String? = null
        var position: CurrentLocationInfo? = null
        lateinit var sdk: NaviHelper
        val listener = object : NaviHelperEventListener {
            override fun onCurrentLocationInfo(currentLocationInfo: CurrentLocationInfo) {
                position = currentLocationInfo
                received.countDown()
            }
        }
        instrumentation.runOnMainSync {
            sdk = NaviHelper(instrumentation.targetContext)
            sdk.initialize(onConnected = { connected.countDown() }, onFailed = { connectionFailure = it.message; connected.countDown() })
        }
        try {
            assertTrue("Navigation SDK connection timed out", connected.await(10, TimeUnit.SECONDS))
            assertTrue("Navigation SDK connection failed: $connectionFailure", connectionFailure == null)
            instrumentation.runOnMainSync { sdk.addListener(listener); sdk.getCurrentLocationInfo() }
            val replied = received.await(15, TimeUnit.SECONDS)
            val result = JSONObject().put("callback_received", replied)
            position?.let { result.put("latitude", it.latitude).put("longitude", it.longitude) }
            instrumentation.sendStatus(2, Bundle().apply { putString("navigation_position", result.toString()) })
            assertTrue("getCurrentLocationInfo returned no callback", replied)
        } finally {
            instrumentation.runOnMainSync { sdk.removeListener(listener); sdk.release() }
        }
    }
}
