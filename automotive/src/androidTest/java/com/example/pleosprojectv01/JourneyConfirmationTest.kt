package com.example.pleosprojectv01

import android.content.Intent
import android.view.ViewGroup
import android.webkit.WebView
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.matcher.ViewMatchers.withText
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.matcher.ViewMatchers.isAssignableFrom
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.util.concurrent.atomic.AtomicReference

class JourneyConfirmationTest {
    @Test fun webConfirmationPreservesCancelAndApprove() {
        val i = InstrumentationRegistry.getInstrumentation()
        assumeTrue(InstrumentationRegistry.getArguments().getString("tmap_confirm") == "true")
        val activity = i.startActivitySync(Intent(i.targetContext, JourneyActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        val web = (activity.findViewById<ViewGroup>(android.R.id.content).getChildAt(0) as WebView)
        i.runOnMainSync {
            web.stopLoading()
            web.loadDataWithBaseURL("http://10.0.2.2:8765/", """
                <html><meta name="viewport" content="width=device-width,initial-scale=1">
                <body style="margin:0"><button id="probe" style="width:100vw;height:100vh"
                onclick="document.title=confirm('동행 경로 확인창 회귀 테스트')?'approved':'cancelled'">Confirm</button></body></html>
            """.trimIndent(), "text/html", "utf-8", null)
        }
        fun waitFor(value: AtomicReference<String?>): String? {
            val end = System.currentTimeMillis()+10000
            while (value.get()==null && System.currentTimeMillis()<end) Thread.sleep(100)
            return value.get()
        }
        val loadedBy = System.currentTimeMillis()+15000
        while (System.currentTimeMillis()<loadedBy) {
            val ready = AtomicReference<String?>(null)
            i.runOnMainSync { web.evaluateJavascript("!!document.getElementById('probe')") { ready.set(it) } }
            if (waitFor(ready)=="true") break
            Thread.sleep(200)
        }
        for ((button, expected) in listOf("취소" to "\"cancelled\"", "확인" to "\"approved\"")) {
            onView(isAssignableFrom(WebView::class.java)).perform(click())
            val dialogBy = System.currentTimeMillis()+5000
            while (System.currentTimeMillis()<dialogBy && runCatching {
                onView(withText(button)).check(matches(isDisplayed()))
            }.isFailure) Thread.sleep(100)
            onView(withText(button)).perform(click())
            val result = AtomicReference<String?>(null)
            i.runOnMainSync { web.evaluateJavascript("document.title") { result.set(it) } }
            assertEquals(expected, waitFor(result))
        }
    }
}
