#include <Argus/Argus.h>

#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <numeric>
#include <sstream>
#include <string>
#include <vector>

namespace {

std::string jsonEscape(const std::string &value)
{
    std::ostringstream escaped;
    for (const unsigned char character : value)
    {
        switch (character)
        {
        case '\"': escaped << "\\\""; break;
        case '\\': escaped << "\\\\"; break;
        case '\b': escaped << "\\b"; break;
        case '\f': escaped << "\\f"; break;
        case '\n': escaped << "\\n"; break;
        case '\r': escaped << "\\r"; break;
        case '\t': escaped << "\\t"; break;
        default:
            if (character < 0x20)
            {
                static const char hex[] = "0123456789abcdef";
                escaped << "\\u00" << hex[(character >> 4) & 0xf] << hex[character & 0xf];
            }
            else
            {
                escaped << character;
            }
        }
    }
    return escaped.str();
}

std::string rationalJson(uint64_t numerator, uint64_t denominator)
{
    if (denominator == 0)
        denominator = 1;
    const uint64_t divisor = std::gcd(numerator, denominator);
    std::ostringstream output;
    output << "{\"numerator\":" << numerator / divisor
           << ",\"denominator\":" << denominator / divisor << "}";
    return output.str();
}

double framesPerSecond(uint64_t durationNanoseconds)
{
    return durationNanoseconds == 0
        ? 0.0
        : 1000000000.0 / static_cast<double>(durationNanoseconds);
}

bool parseSensorId(const char *value, size_t *sensorId)
{
    if (!value || !sensorId || value[0] == '-')
        return false;
    errno = 0;
    char *end = nullptr;
    const unsigned long parsed = std::strtoul(value, &end, 10);
    if (errno != 0 || end == value || *end != '\0')
        return false;
    *sensorId = static_cast<size_t>(parsed);
    return true;
}

} // namespace

int main(int argc, char **argv)
{
    size_t sensorId = 0;
    if (argc == 3 && std::string(argv[1]) == "--sensor-id")
    {
        if (!parseSensorId(argv[2], &sensorId))
        {
            std::cerr << "invalid sensor id\n";
            return EXIT_FAILURE;
        }
    }
    else if (argc != 1)
    {
        std::cerr << "usage: " << argv[0] << " [--sensor-id N]\n";
        return EXIT_FAILURE;
    }

    // Deliberately create only a provider and read immutable camera properties.
    // Creating a CaptureSession here would compete with nvarguscamerasrc.
    Argus::UniqueObj<Argus::CameraProvider> provider(Argus::CameraProvider::create());
    Argus::ICameraProvider *providerInterface =
        Argus::interface_cast<Argus::ICameraProvider>(provider);
    if (!providerInterface)
    {
        std::cerr << "failed to create Argus CameraProvider\n";
        return EXIT_FAILURE;
    }

    std::vector<Argus::CameraDevice *> devices;
    const Argus::Status deviceStatus = providerInterface->getCameraDevices(&devices);
    if (deviceStatus != Argus::STATUS_OK)
    {
        std::cerr << "failed to enumerate Argus camera devices\n";
        return EXIT_FAILURE;
    }
    if (sensorId >= devices.size())
    {
        std::cerr << "sensor id " << sensorId << " is not available (device count "
                  << devices.size() << ")\n";
        return EXIT_FAILURE;
    }

    Argus::ICameraProperties *properties =
        Argus::interface_cast<Argus::ICameraProperties>(devices[sensorId]);
    if (!properties)
    {
        std::cerr << "failed to obtain Argus camera properties\n";
        return EXIT_FAILURE;
    }

    std::vector<Argus::SensorMode *> modes;
    const Argus::Status modeStatus = properties->getAllSensorModes(&modes);
    if (modeStatus != Argus::STATUS_OK || modes.empty())
    {
        std::cerr << "failed to enumerate Argus sensor modes\n";
        return EXIT_FAILURE;
    }

    std::ostringstream json;
    json.setf(std::ios::fixed);
    json.precision(6);
    json << "{\"schema_version\":1"
         << ",\"sensor_id\":" << sensorId
         << ",\"model_name\":\"" << jsonEscape(properties->getModelName()) << "\""
         << ",\"module_string\":\"" << jsonEscape(properties->getModuleString()) << "\""
         << ",\"provenance\":\"libargus\""
         << ",\"modes\":[";

    bool first = true;
    for (size_t index = 0; index < modes.size(); ++index)
    {
        Argus::ISensorMode *mode = Argus::interface_cast<Argus::ISensorMode>(modes[index]);
        if (!mode)
            continue;
        const Argus::Size2D<uint32_t> resolution = mode->getResolution();
        const Argus::Range<uint64_t> duration = mode->getFrameDurationRange();
        const uint64_t fastestDuration = duration.min();
        const uint64_t slowestDuration = duration.max();
        if (!first)
            json << ',';
        first = false;
        json << "{\"id\":\"argus:" << index << "\""
             << ",\"sensor_mode_index\":" << index
             << ",\"width\":" << resolution.width()
             << ",\"height\":" << resolution.height()
             << ",\"native_width\":" << resolution.width()
             << ",\"native_height\":" << resolution.height()
             << ",\"pixel_format\":\"NV12\""
             << ",\"min_fps\":" << framesPerSecond(slowestDuration)
             << ",\"max_fps\":" << framesPerSecond(fastestDuration)
             << ",\"min_fps_rational\":" << rationalJson(1000000000ULL, slowestDuration)
             << ",\"max_fps_rational\":" << rationalJson(1000000000ULL, fastestDuration)
             << ",\"fps_values\":[]"
             << ",\"fps_type\":\"range\""
             << ",\"provenance\":\"libargus\""
             << ",\"status\":\"advertised\"}";
    }
    json << "]}";
    std::cout << json.str() << '\n';
    return first ? EXIT_FAILURE : EXIT_SUCCESS;
}
