package com.cloud42labo.serendipityspot.location

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.cloud42labo.serendipityspot.data.SpotLocalCache
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * ジオフェンスは端末再起動で消えるため、起動直後にローカルキャッシュから張り直す。
 * この時点ではまだGoogleサインインやスプレッドシートへの疎通は行わない
 * （次回アプリを開いたタイミングで最新化される）。
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return

        val appContext = context.applicationContext
        val pendingResult = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val cachedSpots = SpotLocalCache.load(appContext)
                if (cachedSpots.isNotEmpty()) {
                    GeofenceHelper(appContext).resync(cachedSpots)
                }
            } finally {
                pendingResult.finish()
            }
        }
    }
}
