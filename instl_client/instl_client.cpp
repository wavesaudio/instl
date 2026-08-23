#include "fstring/fstring.h"
#include "jsonland/json_node.h"

#include <atomic>
#include <charconv>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <utility>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
using SocketHandle = SOCKET;
constexpr SocketHandle kInvalidSocket = INVALID_SOCKET;
#else
#include <netdb.h>
#include <sys/socket.h>
#include <unistd.h>
using SocketHandle = int;
constexpr SocketHandle kInvalidSocket = -1;
#endif

namespace fs = std::filesystem;

namespace {

using namespace std::string_view_literals;
using Json = jsonland::json_node;

std::atomic_bool interrupted{false};

void on_interrupt(int) {
    interrupted.store(true);
}

class SocketRuntime {
public:
    SocketRuntime() {
#ifdef _WIN32
        WSADATA data{};
        if (WSAStartup(MAKEWORD(2, 2), &data) != 0) {
            throw std::runtime_error("WSAStartup failed");
        }
#endif
    }

    ~SocketRuntime() {
#ifdef _WIN32
        WSACleanup();
#endif
    }
};

class Socket {
public:
    explicit Socket(SocketHandle handle = kInvalidSocket) : handle_(handle) {}
    Socket(const Socket&) = delete;
    Socket& operator=(const Socket&) = delete;
    Socket(Socket&& other) noexcept : handle_(other.handle_) { other.handle_ = kInvalidSocket; }
    ~Socket() { close(); }

    SocketHandle get() const { return handle_; }

private:
    void close() {
        if (handle_ == kInvalidSocket) {
            return;
        }
#ifdef _WIN32
        closesocket(handle_);
#else
        ::close(handle_);
#endif
        handle_ = kInvalidSocket;
    }

    SocketHandle handle_;
};

void read_small_file(const fs::path& path, fstr::fstr_ref contents) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        throw std::runtime_error("cannot open local server file");
    }

    contents.clear();
    stream.read(contents.data(), static_cast<std::streamsize>(contents.capacity()));
    const auto bytes_read = static_cast<std::size_t>(stream.gcount());

    // A fixed-size local file must fit without truncation.
    if (bytes_read == contents.capacity()) {
        char extra_byte{};
        if (stream.get(extra_byte)) {
            throw std::runtime_error("local server file is larger than expected");
        }
    }
    contents.data()[bytes_read] = '\0';
    contents.reposition_end();
}

fs::path default_discovery_path() {
#ifdef _WIN32
    const char* root = std::getenv("LOCALAPPDATA");
    if (!root) {
        throw std::runtime_error("LOCALAPPDATA is not set");
    }
    return fs::path(root) / "Waves Audio" / "instl" / "server.json";
#else
    const char* root = std::getenv("HOME");
    if (!root) {
        throw std::runtime_error("HOME is not set");
    }
    return fs::path(root) / "Library" / "Application Support" / "Waves Audio" / "instl" / "server.json";
#endif
}

struct Endpoint {
    fstr::fstr15 host;
    int port{};
    fstr::fstr15 security;
    fstr::fstr63 token;
    fstr::fstr127 monitor_url;
};

const Json& required_member(const Json& object, std::string_view key) {
    if (!object.is_object() || !object.contains(key)) {
        throw std::runtime_error("JSON object is missing a required member");
    }
    return object[key];
}

std::string_view json_text(const Json& value) {
    if (!value.is_string()) {
        throw std::runtime_error("JSON member is not a string");
    }
    return value.get_string();
}

void assign_checked(fstr::fstr_ref destination, std::string_view source) {
    if (source.size() > destination.capacity()) {
        throw std::runtime_error("server text field is larger than expected");
    }
    destination = source;
}

Endpoint discover(const fs::path& path) {
    // Discovery keeps callers independent of the server's ephemeral port.
    fstr::fstr2047 discovery_text;
    read_small_file(path, discovery_text);
    jsonland::json_doc value;
    if (value.parse(discovery_text.sv()) != 0) {
        throw std::runtime_error("cannot parse the server discovery file");
    }

    Endpoint endpoint;
    assign_checked(endpoint.host, json_text(required_member(value, "host"sv)));
    const Json& port = required_member(value, "port"sv);
    if (!port.is_int()) {
        throw std::runtime_error("discovery port is not an integer");
    }
    endpoint.port = port.get_int<int>();
    assign_checked(endpoint.security, json_text(required_member(value, "security"sv)));
    assign_checked(endpoint.monitor_url, json_text(required_member(value, "monitor_url"sv)));

    if (endpoint.host != "127.0.0.1"sv || endpoint.port < 1 || endpoint.port > 65535) {
        throw std::runtime_error("discovery file contains a non-loopback or invalid endpoint");
    }
    if (endpoint.security == "token"sv) {
        // Keep the credential separate from public connection metadata.
        const std::string_view token_path_text = json_text(required_member(value, "token_file"sv));
        const fs::path token_path(token_path_text.begin(), token_path_text.end());
        read_small_file(token_path, endpoint.token);
        endpoint.token.trim();
        if (endpoint.token.empty()) {
            throw std::runtime_error("server token file is empty");
        }
    } else if (endpoint.security != "none"sv) {
        throw std::runtime_error("unsupported server security mode");
    }
    return endpoint;
}

Socket connect_to(std::string_view host, int port) {
    addrinfo hints{};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    addrinfo* results = nullptr;

    fstr::fstr63 null_terminated_host;
    assign_checked(null_terminated_host, host);
    fstr::fstr7 service(port);
    const int status = getaddrinfo(
        null_terminated_host.c_str(), service.c_str(), &hints, &results
    );
    if (status != 0) {
        throw std::runtime_error("cannot resolve server endpoint");
    }

    SocketHandle connected = kInvalidSocket;
    for (addrinfo* current = results; current; current = current->ai_next) {
        SocketHandle candidate = ::socket(current->ai_family, current->ai_socktype, current->ai_protocol);
        if (candidate == kInvalidSocket) {
            continue;
        }
        if (::connect(candidate, current->ai_addr, static_cast<int>(current->ai_addrlen)) == 0) {
            connected = candidate;
            break;
        }
#ifdef _WIN32
        closesocket(candidate);
#else
        ::close(candidate);
#endif
    }
    freeaddrinfo(results);
    if (connected == kInvalidSocket) {
        throw std::runtime_error("cannot connect to instl server");
    }
    return Socket(connected);
}

void send_all(SocketHandle socket, std::string_view data) {
    std::size_t sent = 0;
    while (sent < data.size()) {
        const auto remaining = data.size() - sent;
        const int count = ::send(socket, data.data() + sent, static_cast<int>(remaining), 0);
        if (count <= 0) {
            throw std::runtime_error("connection closed while sending request");
        }
        sent += static_cast<std::size_t>(count);
    }
}

std::string receive_all(SocketHandle socket) {
    constexpr std::size_t max_response = 32 * 1024 * 1024;
    std::string response;
    char buffer[8192];
    while (true) {
        const int count = ::recv(socket, buffer, sizeof(buffer), 0);
        if (count == 0) {
            break;
        }
        if (count < 0) {
            throw std::runtime_error("connection failed while receiving response");
        }
        response.append(buffer, static_cast<std::size_t>(count));
        if (response.size() > max_response) {
            throw std::runtime_error("server response exceeds 32 MiB");
        }
    }
    return response;
}

Json rpc(const Endpoint& endpoint, std::string_view method, const Json& params) {
    static std::uint64_t next_id = 0;
    // JSON bodies can grow with command arguments, so they stay dynamically sized.
    Json request(jsonland::object_t, 4);
    request["jsonrpc"sv] = "2.0";
    request["id"sv] = ++next_id;
    request["method"sv] = method;
    request["params"sv].clone_value_of(params);
    const std::string body = request.dump();

    // One request per connection keeps the HTTP implementation small and robust.
    fstr::fstr511 request_headers(
        "POST /rpc HTTP/1.1\r\nHost: ", endpoint.host.sv(), ':', endpoint.port,
        "\r\nContent-Type: application/json\r\nContent-Length: ", body.size(),
        "\r\nConnection: close\r\n"
    );
    if (!endpoint.token.empty()) {
        request_headers += "Authorization: Bearer ";
        request_headers += endpoint.token.sv();
        request_headers += "\r\n";
    }
    request_headers += "\r\n";

    Socket socket = connect_to(endpoint.host.sv(), endpoint.port);
    send_all(socket.get(), request_headers.sv());
    send_all(socket.get(), body);
    const std::string response = receive_all(socket.get());
    const std::string_view response_view(response.data(), response.size());
    const auto header_end = response_view.find("\r\n\r\n"sv);
    if (header_end == std::string_view::npos) {
        throw std::runtime_error("invalid HTTP response");
    }
    const auto first_space = response_view.find(' ');
    if (first_space == std::string_view::npos || response_view.size() < first_space + 4) {
        throw std::runtime_error("invalid HTTP status line");
    }

    int http_status = 0;
    const std::string_view status_text = response_view.substr(first_space + 1, 3);
    const auto status_parse = std::from_chars(
        status_text.data(), status_text.data() + status_text.size(), http_status
    );
    if (status_parse.ec != std::errc()) {
        throw std::runtime_error("invalid HTTP status code");
    }
    if (http_status != 200) {
        fstr::fstr63 message("server returned HTTP ", http_status);
        throw std::runtime_error(message.c_str());
    }

    const std::string_view response_body = response_view.substr(header_end + 4);
    jsonland::json_doc decoded;
    if (decoded.parse(response_body) != 0) {
        throw std::runtime_error("cannot parse the JSON-RPC response");
    }
    if (!decoded.is_object()) {
        throw std::runtime_error("JSON-RPC response is not an object");
    }
    if (decoded.contains("error"sv)) {
        const Json& error = required_member(decoded, "error"sv);
        const int error_code = required_member(error, "code"sv).get_int<int>();
        const std::string_view error_text = json_text(required_member(error, "message"sv));
        fstr::fstr255 message("JSON-RPC ", error_code, ": ", error_text);
        throw std::runtime_error(message.c_str());
    }
    return required_member(decoded, "result"sv).clone();
}

Json rpc(const Endpoint& endpoint, std::string_view method) {
    Json params(jsonland::object_t);
    return rpc(endpoint, method, params);
}

Json job_id_params(std::string_view job_id) {
    Json params(jsonland::object_t, 1);
    params["job_id"sv] = job_id;
    return Json(std::move(params));
}

bool is_terminal(std::string_view status) {
    return status == "succeeded"sv || status == "failed"sv || status == "aborted"sv;
}

int follow(const Endpoint& endpoint, std::string_view job_id) {
    std::uint64_t after = 0;
    bool abort_sent = false;
    while (true) {
        if (interrupted.load() && !abort_sent) {
            std::cerr << "\nrequesting abort for " << job_id << "...\n";
            rpc(endpoint, "jobs.abort"sv, job_id_params(job_id));
            abort_sent = true;
        }

        Json poll_params(jsonland::object_t, 3);
        poll_params["job_id"sv] = job_id;
        poll_params["after"sv] = after;
        poll_params["limit"sv] = 1000;
        const Json result = rpc(endpoint, "jobs.poll"sv, poll_params);
        if (result.get_value("events_dropped"sv, false)) {
            std::cerr << "[some earlier output was discarded by the server]\n";
        }
        const Json& events = required_member(result, "events"sv);
        if (!events.is_array()) {
            throw std::runtime_error("JSON-RPC events member is not an array");
        }
        for (const auto& event : events) {
            const std::string_view stream = json_text(required_member(event, "stream"sv));
            std::ostream* output = &std::cerr;
            if (stream == "stdout"sv) {
                output = &std::cout;
            }
            const std::string_view text = json_text(required_member(event, "text"sv));
            output->write(text.data(), static_cast<std::streamsize>(text.size()));
            output->flush();
            const Json& sequence = required_member(event, "seq"sv);
            if (!sequence.is_int()) {
                throw std::runtime_error("JSON-RPC event sequence is not an integer");
            }
            after = sequence.get_int<std::uint64_t>();
        }
        const std::string_view status = json_text(required_member(result, "status"sv));
        if (is_terminal(status)) {
            const Json& return_code_member = required_member(result, "return_code"sv);
            if (return_code_member.is_int()) {
                const int return_code = return_code_member.get_int<int>();
                if (return_code < 0) {
                    return 1;
                }
                return return_code;
            }
            if (status == "succeeded"sv) {
                return 0;
            }
            return 1;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(150));
    }
}

Json launch(const Endpoint& endpoint, int argc, char* argv[], int first_argument) {
    std::string_view cwd;
    int index = first_argument;
    if (index + 1 < argc && std::string_view(argv[index]) == "--cwd"sv) {
        cwd = argv[index + 1];
        index += 2;
    }
    if (index < argc && std::string_view(argv[index]) == "--"sv) {
        ++index;
    }
    if (index >= argc) {
        throw std::runtime_error("run/launch requires instl arguments");
    }
    Json params(jsonland::object_t, 2);
    Json& args = params.append_array("args"sv, static_cast<std::size_t>(argc - index));
    for (; index < argc; ++index) {
        args.push_back(argv[index]);
    }
    if (!cwd.empty()) {
        params["cwd"sv] = cwd;
    }
    return rpc(endpoint, "jobs.launch"sv, params);
}

void print_usage() {
    std::cerr
        << "Usage: instl-client [--discovery PATH] COMMAND [ARGS]\n"
        << "Commands:\n"
        << "  ping                         Check server connectivity\n"
        << "  list                         List known jobs\n"
        << "  status JOB_ID                Show one job as JSON\n"
        << "  abort JOB_ID                 Abort a queued or running job\n"
        << "  follow JOB_ID                Stream output until completion\n"
        << "  launch [--cwd DIR] -- ARGS   Start an instl command and print its ID\n"
        << "  run [--cwd DIR] -- ARGS      Start, stream, and return the command exit code\n"
        << "  monitor-url                  Print the browser monitoring URL\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    try {
        // Winsock startup is a no-op on macOS.
        SocketRuntime socket_runtime;
        fs::path discovery_path = default_discovery_path();
        int index = 1;
        if (index + 1 < argc && std::string_view(argv[index]) == "--discovery"sv) {
            discovery_path = argv[index + 1];
            index += 2;
        }
        if (index >= argc) {
            print_usage();
            return 2;
        }

        const Endpoint endpoint = discover(discovery_path);
        const std::string_view command = argv[index++];
        if (command == "ping"sv) {
            rpc(endpoint, "system.ping"sv).dump(
                std::cout, jsonland::dump_style::pretty
            ) << '\n';
        } else if (command == "list"sv) {
            const Json jobs = rpc(endpoint, "jobs.list"sv);
            if (!jobs.is_array()) {
                throw std::runtime_error("JSON-RPC jobs result is not an array");
            }
            for (const auto& job : jobs) {
                const std::string_view listed_job_id = json_text(required_member(job, "job_id"sv));
                const std::string_view listed_status = json_text(required_member(job, "status"sv));
                std::cout.write(listed_job_id.data(), static_cast<std::streamsize>(listed_job_id.size()));
                std::cout << "  ";
                std::cout.write(listed_status.data(), static_cast<std::streamsize>(listed_status.size()));
                std::cout << "  ";
                const Json& arguments = required_member(job, "args"sv);
                if (!arguments.is_array()) {
                    throw std::runtime_error("JSON-RPC job arguments are not an array");
                }
                for (const auto& argument : arguments) {
                    const std::string_view argument_text = json_text(argument);
                    std::cout.write(
                        argument_text.data(), static_cast<std::streamsize>(argument_text.size())
                    );
                    std::cout << ' ';
                }
                std::cout << '\n';
            }
        } else if (command == "status"sv || command == "abort"sv || command == "follow"sv) {
            if (index >= argc) {
                throw std::runtime_error("command requires a job ID");
            }
            const std::string_view job_id = argv[index];
            if (command == "status"sv) {
                rpc(endpoint, "jobs.get"sv, job_id_params(job_id)).dump(
                    std::cout, jsonland::dump_style::pretty
                ) << '\n';
            } else if (command == "abort"sv) {
                rpc(endpoint, "jobs.abort"sv, job_id_params(job_id)).dump(
                    std::cout, jsonland::dump_style::pretty
                ) << '\n';
            } else {
                std::signal(SIGINT, on_interrupt);
                return follow(endpoint, job_id);
            }
        } else if (command == "launch"sv || command == "run"sv) {
            const Json job = launch(endpoint, argc, argv, index);
            fstr::fstr63 job_id;
            assign_checked(job_id, json_text(required_member(job, "job_id"sv)));
            std::cout << job_id.sv() << '\n' << std::flush;
            if (command == "run"sv) {
                std::signal(SIGINT, on_interrupt);
                return follow(endpoint, job_id.sv());
            }
        } else if (command == "monitor-url"sv) {
            std::cout << endpoint.monitor_url.sv();
            if (!endpoint.token.empty()) {
                std::cout << '#' << endpoint.token.sv();
            }
            std::cout << '\n';
        } else {
            print_usage();
            return 2;
        }
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "instl-client: " << ex.what() << '\n';
        return 1;
    }
}
