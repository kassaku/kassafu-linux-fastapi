#include <cstdlib>
#include <string>

bool makePayment(int amount_cents, const std::string& order_id) {
    std::string cmd = "python kassafu.py --pay --amount " + 
                      std::to_string(amount_cents) + 
                      " --order " + order_id + " --json";
    
    // Execute and capture output
    FILE* pipe = popen(cmd.c_str(), "r");
    char buffer[128];
    std::string result;
    
    while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
        result += buffer;
    }
    pclose(pipe);
    
    // Parse JSON to check success
    return result.find("\"success\":true") != std::string::npos;
}

