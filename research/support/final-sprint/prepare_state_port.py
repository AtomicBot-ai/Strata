"""Port just the validated state primitive; diagnostics and teacher forcing stay in the research binary."""
from pathlib import Path
import subprocess
base=Path.cwd()
prod=base/'Atomic-Turbine'
orig=prod/'engine/src/inkling2'
research=base/'.work/strata-scaling/review-fork-engine/src/inkling2'
dst=base/'.work/final-sprint/state-port'
dst.mkdir(parents=True,exist_ok=True)
for name in ('ink_backend.h','metal/ink_metal_backend.mm','ink_serve.h'):
    txt=(orig/name).read_text() if name=='ink_serve.h' else (research/name).read_text()
    if name=='ink_backend.h':txt=txt.replace('save_prefix(int, int)','save_prefix(int, int, size_t)')
    if name.endswith('.mm'):
        txt=txt.replace('save_prefix(int slot, int tokens)', 'save_prefix(int slot, int tokens, size_t budget)')
        a=txt.index('        runner_.snapshot_slot(slot, saved->conv);');b=txt.index('        for (int v',a)
        txt=txt[:a]+'''        const auto& c = mod_.man.c;
        const size_t row_bytes = (size_t)c.n_kv * c.head_dim * sizeof(uint16_t);
        // Two KV convolution histories and two hidden-state histories, three rows each.
        const size_t conv_bytes = runner_.sc_hist_k.empty() ? 0 :
            6ull * c.n_visits * (size_t(c.n_kv) * c.head_dim + c.hidden) * sizeof(float);
        if (conv_bytes > budget) return nullptr;
        saved->payload_bytes = conv_bytes;
'''+txt[b:]
        txt=txt.replace('                saved->kv.push_back(', '                if (count > budget - saved->payload_bytes) return nullptr;\n                saved->kv.push_back(')
        txt=txt.replace('        void* region = mmap(', '        runner_.snapshot_slot(slot, saved->conv);\n        void* region = mmap(')
    if name=='ink_serve.h':
        txt=txt.replace('#include <deque>', '#include <charconv>\n#include <sstream>\n#include <deque>')
        i=txt.index('    proto("INFO engine=strata-inkling')
        txt=txt[:i]+'''    // A positive budget opts the trusted native transport into one process-local snapshot.
    unsigned snapshot_mib = 0;
    if (const char* opt = std::getenv("TURBINE_SNAPSHOT_MIB")) {
        const char* end = opt + std::strlen(opt);
        const auto parsed = std::from_chars(opt, end, snapshot_mib);
        if (parsed.ec != std::errc{} || parsed.ptr != end || snapshot_mib > 32768) {
            std::fprintf(stderr, "TURBINE_SNAPSHOT_MIB must be 0..32768\\n");
            return 1;
        }
    }
    const bool state_enabled = snapshot_mib && !use_dspark && P <= 2 &&
        std::string(backend.backend_name()) == "metal" && std::string(kv_str) == "fp16" && cfg.vision_path.empty();
'''+txt[i:]
        txt=txt.replace('parallel=%d ckpt_key=1"', 'parallel=%d ckpt_key=1 native_fork=%d"').replace('c.image_token_id, kMaxParallelSlots);','c.image_token_id, kMaxParallelSlots, int(state_enabled));')
        txt=txt.replace('    bool quit_requested = false;', '''    std::unique_ptr<InkPrefixCheckpoint> saved;
    std::vector<int32_t> saved_ids;
    uint64_t generation = 0;
    if (state_enabled) {
        std::random_device random;
        generation = (uint64_t(random()) << 32) ^ random();
    }
    bool quit_requested = false;''')
        i=txt.index('        if (line.empty()) return true;',txt.index('auto handle_line'))+len('        if (line.empty()) return true;')
        txt=txt[:i]+'''
        if (line.rfind("STATE_", 0) == 0) {
            if (!state_enabled) { proto("ERR native fork disabled"); return true; }
            std::istringstream in(line);
            std::string op, extra;
            int slot = -1;
            uint64_t handle = 0;
            in >> op;
            if (op == "STATE_DROP") {
                if (!(in >> handle) || in >> extra || !saved || handle != generation) {
                    proto("ERR invalid snapshot handle"); return true;
                }
                saved.reset();
                std::vector<int32_t>().swap(saved_ids);
                proto("DROPPED");
                return true;
            }
            if ((op != "STATE_SAVE" && op != "STATE_RESTORE") || !(in >> slot) || slot < 0 || slot >= P ||
                reqs[slot].active || (op == "STATE_RESTORE" && !(in >> handle)) || in >> extra) {
                proto("ERR invalid command or busy slot"); return true;
            }
            auto& rq = reqs[slot];
            try {
                if (op == "STATE_SAVE") {
                    const size_t budget = size_t(snapshot_mib) << 20;
                    const size_t ids_bytes = rq.cached_prefix.size() * sizeof(int32_t);
                    // A second live image must not make transient memory exceed the configured payload budget.
                    if (saved || !ids_bytes || ids_bytes >= budget) {
                        proto("ERR drop existing snapshot or check source and budget"); return true;
                    }
                    auto next = backend.save_prefix(slot, int(rq.cached_prefix.size()), budget - ids_bytes);
                    if (!next) { proto("ERR snapshot unavailable or over budget"); return true; }
                    saved_ids = rq.cached_prefix;
                    saved = std::move(next);
                    ++generation;
                    proto("SAVED %llu %zu %zu", (unsigned long long)generation, saved_ids.size(), saved->payload_bytes + ids_bytes);
                } else {
                    if (!saved || handle != generation) { proto("ERR invalid snapshot handle"); return true; }
                    // Allocate host metadata before touching any destination state.
                    auto ids = saved_ids;
                    saved->restore(slot);
                    rq.cached_prefix.swap(ids);
                    rq.prompt_ckpt_prefix.clear();
                    rq.shared_prefix.clear();
                    proto("RESTORED %zu", saved_ids.size());
                }
            } catch (const std::bad_alloc&) {
                proto("ERR snapshot allocation failed");
            }
            return true;
        }
'''+txt[i:]
        # Compile-time test-only exposure of the endpoint for same-shape regression checks.
        txt=txt.replace('        bool use_cand = cand_ok', '        bool use_cand =\n#ifdef TURBINE_TEST_LOGITS\n            !std::getenv("TURBINE_TEST_LOGITS") &&\n#endif\n            cand_ok')
        marker='\n            rq.hist.push_back(tok);'
        txt=txt.replace(marker,'''
#ifdef TURBINE_TEST_LOGITS
            if (lg && std::getenv("TURBINE_TEST_LOGITS") && rq.generated + 1 == rq.max_new) {
                const auto* bytes = reinterpret_cast<const unsigned char*>(lg);
                static constexpr char hex[] = "0123456789abcdef";
                std::string out(2 * V * sizeof(float), '0');
                for (size_t j = 0; j < out.size()/2; ++j) {
                    out[2*j] = hex[bytes[j] >> 4];
                    out[2*j+1] = hex[bytes[j] & 15];
                }
                std::cout << "LOGITS " << rq.req_id << " " << out << std::endl;
            }
#endif
'''+marker)
    out=dst/name
    out.parent.mkdir(exist_ok=True,parents=True);out.write_text(txt)
patch=b''.join(subprocess.run(['diff','-u','--label','a/engine/src/inkling2/'+n,'--label','b/engine/src/inkling2/'+n,str(orig/n),str(dst/n)],capture_output=True).stdout for n in ('ink_backend.h','metal/ink_metal_backend.mm','ink_serve.h'))
(dst/'native-state.patch').write_bytes(patch)
