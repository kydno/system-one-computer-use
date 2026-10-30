import Foundation

/// OpenRouter's public model catalog, which the settings box searches for the
/// reviewer: the answer model `clicker` hands the screen to whenever the
/// classifier stops (`CLICKER_ANSWER_MODEL`). Neither request needs a key.
enum OpenRouter {

    struct Model: Identifiable, Equatable, Sendable {
        let id: String
        let name: String
        let created: Double
        /// Dollars per token, as OpenRouter gives them.
        let prompt: Double
        let completion: Double
    }

    struct Endpoint: Equatable, Sendable {
        let provider: String
        let tag: String
        let prompt: Double
        let completion: Double

        /// "OpenAI · flex" for the tag `openai/flex`, the provider alone otherwise.
        var title: String {
            guard let slash = tag.firstIndex(of: "/") else { return provider }
            return "\(provider) · \(tag[tag.index(after: slash)...])"
        }
    }

    /// The models a reviewer can be: they read a screenshot and write text back.
    /// Fetched once per launch; a failure is not kept, so the next search tries again.
    static func models() async throws -> [Model] {
        if let cached = await Cache.shared.models { return cached }
        let data = try await get(K.Reviewer.modelsURL)
        let list = try JSONDecoder().decode(ModelList.self, from: data).data
        let models = list.compactMap { raw -> Model? in
            guard raw.architecture.input_modalities.contains("image"),
                  raw.architecture.output_modalities.contains("text"),
                  !raw.id.hasSuffix(":batch")
            else { return nil }
            return Model(
                id: raw.id,
                name: raw.name,
                created: raw.created ?? 0,
                prompt: Double(raw.pricing.prompt) ?? 0,
                completion: Double(raw.pricing.completion) ?? 0
            )
        }
        await Cache.shared.store(models)
        return models
    }

    /// The providers serving `model` now, cheapest first: input price, then output.
    static func endpoints(for model: String) async throws -> [Endpoint] {
        let path = K.Reviewer.endpointsURL.replacingOccurrences(of: "{id}", with: model)
        guard let url = URL(string: path) else { return [] }
        let data = try await get(url)
        let list = try JSONDecoder().decode(EndpointList.self, from: data).data.endpoints
        return list
            .filter { ($0.status ?? 0) == 0 }
            .map {
                Endpoint(
                    provider: $0.provider_name,
                    tag: $0.tag ?? $0.provider_name,
                    prompt: Double($0.pricing.prompt) ?? 0,
                    completion: Double($0.pricing.completion) ?? 0
                )
            }
            .sorted { ($0.prompt, $0.completion) < ($1.prompt, $1.completion) }
    }

    /// The best `count` matches for what was typed. Every word has to appear in
    /// the id or the name; a word that starts one of theirs counts for more, and
    /// so does a shorter, newer model, which is usually the one meant.
    static func search(_ query: String, in models: [Model], count: Int) -> [Model] {
        let words = normalized(query).split(separator: " ").map(String.init)
        guard !words.isEmpty else { return [] }
        let compact = words.joined()

        let scored = models.compactMap { model -> (Model, Double)? in
            let haystack = normalized("\(model.id) \(model.name)")
            let starts = Set(haystack.split(separator: " ").map(String.init))
            var score = 0.0
            for word in words {
                guard haystack.contains(word) else { return nil }
                score += starts.contains { $0.hasPrefix(word) } ? 10 : 3
            }
            let slug = normalized(model.id.split(separator: "/").last.map(String.init) ?? model.id)
                .replacingOccurrences(of: " ", with: "")
            if slug == compact { score += 40 } else if slug.hasPrefix(compact) { score += 20 }
            score -= Double(model.id.count) * 0.05
            // A year newer outweighs twenty characters, so Sonnet 5.5 comes before 5,
            // and Terra before Terra Pro, released the same day.
            score += model.created / K.Reviewer.secondsPerYear
            return (model, score)
        }

        return scored
            .sorted { $0.1 != $1.1 ? $0.1 > $1.1 : $0.0.created > $1.0.created }
            .prefix(count)
            .map(\.0)
    }

    /// Dollars per million tokens, in and out: "$0.50 / $2.50", or "Free".
    static func price(prompt: Double, completion: Double) -> String {
        guard prompt > 0 || completion > 0 else { return "Free" }
        return "\(dollars(prompt)) / \(dollars(completion))"
    }

    private static func dollars(_ perToken: Double) -> String {
        let perMillion = perToken * 1_000_000
        return perMillion < 0.1 ? String(format: "$%.3f", perMillion) : String(format: "$%.2f", perMillion)
    }

    /// Lowercased, with the separators ids use (`-`, `/`, `:`, `_`) read as spaces.
    private static func normalized(_ text: String) -> String {
        let spaced = text.lowercased().map { "-/:_(),".contains($0) ? " " : $0 }
        return String(spaced).split(separator: " ").joined(separator: " ")
    }

    private static func get(_ url: URL) async throws -> Data {
        var request = URLRequest(url: url, timeoutInterval: K.Reviewer.requestTimeout)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await URLSession.shared.data(for: request)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw URLError(.badServerResponse)
        }
        return data
    }

    private actor Cache {
        static let shared = Cache()
        private(set) var models: [Model]?
        func store(_ models: [Model]) { self.models = models }
    }

    // The parts of OpenRouter's replies read here; field names are theirs.

    private struct ModelList: Decodable {
        let data: [RawModel]
    }

    private struct RawModel: Decodable {
        let id: String
        let name: String
        let created: Double?
        let architecture: Architecture
        let pricing: Pricing
    }

    private struct Architecture: Decodable {
        let input_modalities: [String]
        let output_modalities: [String]
    }

    private struct Pricing: Decodable {
        let prompt: String
        let completion: String
    }

    private struct EndpointList: Decodable {
        let data: EndpointData
    }

    private struct EndpointData: Decodable {
        let endpoints: [RawEndpoint]
    }

    private struct RawEndpoint: Decodable {
        let provider_name: String
        let tag: String?
        let status: Int?
        let pricing: Pricing
    }
}

/// How OpenRouter orders the reviewer's providers (`CLICKER_ANSWER_SORT`).
struct ReviewerRouting: Identifiable, Equatable {
    let id: String
    let title: String

    static let modelKey = "CLICKER_ANSWER_MODEL"
    static let key = "CLICKER_ANSWER_SORT"

    static let auto = ReviewerRouting(id: "", title: "Auto")
    static let cheapest = ReviewerRouting(id: "price", title: "Cheapest")
    static let fastest = ReviewerRouting(id: "throughput", title: "Fastest")
    static let all = [auto, cheapest, fastest]

    static func named(_ value: String?) -> ReviewerRouting {
        all.first { $0.id == (value ?? "") } ?? auto
    }
}
