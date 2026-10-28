/*
  ESP32 True DMA ADC -> USB Binary Streamer
  Board: ESP32 Dev Module
  Arduino-ESP32 core: 3.x / ESP-IDF 5.x

  Input:
    GPIO34 = ADC1_CHANNEL_6

  Output packet, little-endian:
    0xAA 0x55                    2 bytes: sync
    uint32_t sequence            4 bytes
    uint16_t sample_count        2 bytes
    uint16_t samples[N]          2N bytes, raw 12-bit ADC values

  Acquisition:
    20,000 samples/s, one ADC1 channel, true DMA stream.

  Hardware requirements:
    - GPIO34 voltage must never go below 0 V or above 3.3 V.
    - Bias audio signal around ~1.65 V.
    - Add an analogue anti-alias LPF before GPIO34.
*/

#include <Arduino.h>

extern "C" {
  #include "esp_adc/adc_continuous.h"
  #include "soc/soc_caps.h"
}

constexpr uint32_t SERIAL_BAUD = 921600;

constexpr uint32_t SAMPLE_RATE = 30000;
constexpr uint16_t SAMPLES_PER_PACKET = 256;

constexpr adc_unit_t ADC_UNIT = ADC_UNIT_1;
constexpr adc_channel_t ADC_CHANNEL = ADC_CHANNEL_6;  // GPIO34

constexpr uint8_t SYNC_0 = 0xAA;
constexpr uint8_t SYNC_1 = 0x55;

adc_continuous_handle_t adcHandle = nullptr;

struct __attribute__((packed)) PacketHeader {
  uint8_t sync0;
  uint8_t sync1;
  uint32_t sequence;
  uint16_t sampleCount;
};

uint16_t sampleBuffer[SAMPLES_PER_PACKET];
uint16_t sampleIndex = 0;
uint32_t sequenceNumber = 0;

void fatalError(const char* message, esp_err_t err) {
  Serial.printf("FATAL: %s, error = %d\n", message, err);

  while (true) {
    delay(1000);
  }
}

void setupADCContinuousDMA() {
  adc_continuous_handle_cfg_t handleConfig = {};
  handleConfig.max_store_buf_size = 4096;
  handleConfig.conv_frame_size = 512;

  esp_err_t err = adc_continuous_new_handle(&handleConfig, &adcHandle);

  if (err != ESP_OK) {
    fatalError("adc_continuous_new_handle failed", err);
  }

  adc_digi_pattern_config_t pattern = {};
  pattern.atten = ADC_ATTEN_DB_12;
  pattern.channel = ADC_CHANNEL;
  pattern.unit = ADC_UNIT;
  pattern.bit_width = ADC_BITWIDTH_12;

  adc_continuous_config_t adcConfig = {};
  adcConfig.pattern_num = 1;
  adcConfig.adc_pattern = &pattern;
  adcConfig.sample_freq_hz = SAMPLE_RATE;
  adcConfig.conv_mode = ADC_CONV_SINGLE_UNIT_1;
  adcConfig.format = ADC_DIGI_OUTPUT_FORMAT_TYPE1;

  err = adc_continuous_config(adcHandle, &adcConfig);

  if (err != ESP_OK) {
    fatalError("adc_continuous_config failed", err);
  }

  err = adc_continuous_start(adcHandle);

  if (err != ESP_OK) {
    fatalError("adc_continuous_start failed", err);
  }
}

void sendPacket() {
  PacketHeader header = {
    SYNC_0,
    SYNC_1,
    sequenceNumber++,
    SAMPLES_PER_PACKET
  };

  Serial.write(
    reinterpret_cast<const uint8_t*>(&header),
    sizeof(header)
  );

  Serial.write(
    reinterpret_cast<const uint8_t*>(sampleBuffer),
    sizeof(sampleBuffer)
  );
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(1200);

  Serial.println("ESP32 DMA ADC USB stream starting...");
  setupADCContinuousDMA();

  // Do not print anything after this point:
  // the serial port now carries binary packets.
  delay(100);
}

void loop() {
  uint8_t dmaBuffer[512];
  uint32_t bytesRead = 0;

  esp_err_t err = adc_continuous_read(
    adcHandle,
    dmaBuffer,
    sizeof(dmaBuffer),
    &bytesRead,
    1000
  );

  if (err == ESP_ERR_TIMEOUT) {
    return;
  }

  if (err != ESP_OK) {
    return;
  }

  for (
    uint32_t i = 0;
    i + SOC_ADC_DIGI_RESULT_BYTES <= bytesRead;
    i += SOC_ADC_DIGI_RESULT_BYTES
  ) {
    auto* result = reinterpret_cast<adc_digi_output_data_t*>(
      &dmaBuffer[i]
    );

    // Type 1 DMA format:
    // bits [15:12] = channel
    // bits [11:0]  = ADC conversion result.
    if (result->type1.channel != ADC_CHANNEL) {
      continue;
    }

    sampleBuffer[sampleIndex++] = result->type1.data & 0x0FFF;

    if (sampleIndex == SAMPLES_PER_PACKET) {
      sendPacket();
      sampleIndex = 0;
    }
  }
}