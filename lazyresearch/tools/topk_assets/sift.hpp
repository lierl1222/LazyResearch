#pragma once
#include "topk_common.hpp"
#include <algorithm>

inline std::vector<TokenScore> candidate_topk(const float* logits, std::size_t vocab, std::size_t k) {
    if (k > vocab) throw std::invalid_argument("k must not exceed vocab");
    if (k == 0) return {};
    std::vector<TokenScore> heap;
    heap.reserve(k);
    for (std::size_t i = 0; i < k; ++i)
        heap.push_back({static_cast<std::uint32_t>(i), logits[i]});
    std::make_heap(heap.begin(), heap.end(), rank_before);
    for (std::size_t i = k; i < vocab; ++i) {
        // Equal scores from later IDs cannot displace the current worst token.
        if (logits[i] > heap.front().score) {
            const TokenScore next{static_cast<std::uint32_t>(i), logits[i]};
            std::size_t pos = 0;
            while (pos < k / 2) {
                std::size_t child = 2 * pos + 1;
                if (child + 1 < k && rank_before(heap[child], heap[child + 1])) ++child;
                if (!rank_before(next, heap[child])) break;
                heap[pos] = heap[child];
                pos = child;
            }
            heap[pos] = next;
        }
    }
    std::sort_heap(heap.begin(), heap.end(), rank_before);
    return heap;
}
