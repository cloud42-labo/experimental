package com.cloud42labo.serendipityspot.data

import android.content.Context
import android.location.Geocoder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.Locale

/** 検索結果の1件。 */
data class PlaceResult(
    val name: String,
    val subtitle: String,
    val lat: Double,
    val lng: Double,
)

/**
 * 住所・駅名・施設名から座標を引く。
 *
 * Android 標準の [Geocoder] を使う。Google Play 開発者サービスが入っている端末では
 * Google のジオコーディングを叩くため、別途 API キーを発行する必要がない。
 * Places API の方が候補の質は高いが、有効化と課金設定が増えるので試作では使わない。
 */
class PlaceSearcher(private val context: Context) {

    suspend fun search(query: String): List<PlaceResult> = withContext(Dispatchers.IO) {
        if (query.isBlank()) return@withContext emptyList()
        if (!Geocoder.isPresent()) return@withContext emptyList()

        val geocoder = Geocoder(context, Locale.JAPAN)
        // 33+ にコールバック版があるが、こちらも動く。分岐を増やす利点が薄いので統一する。
        @Suppress("DEPRECATION")
        val addresses = runCatching { geocoder.getFromLocationName(query, MAX_RESULTS) }
            .getOrNull()
            .orEmpty()

        addresses.mapNotNull { address ->
            val line = address.getAddressLine(0)
            val name = address.featureName ?: line ?: return@mapNotNull null
            PlaceResult(
                name = name,
                subtitle = line.orEmpty(),
                lat = address.latitude,
                lng = address.longitude,
            )
        }
    }

    companion object {
        private const val MAX_RESULTS = 8
    }
}
