package com.cloud42labo.serendipityspot

import android.app.Application
import com.cloud42labo.serendipityspot.notification.NotificationHelper

class SerendipityApp : Application() {
    override fun onCreate() {
        super.onCreate()
        NotificationHelper.ensureChannel(this)
    }
}
