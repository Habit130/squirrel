#include "vendor/rime_api.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

enum {
  kLineMax = 8192,
  kPathMax = 4096,
  kTextMax = 4096
};

static RimeApi *g_api;
static RimeSessionId g_session;
static int g_inited;
static int g_include_text;
static char g_schema[128] = "luna_pinyin";

static uint64_t mono_ns(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static void json_escape(const char *src, char *dst, size_t dst_n) {
  size_t o = 0;
  for (size_t i = 0; src[i] && o + 6 < dst_n; ++i) {
    unsigned char c = (unsigned char)src[i];
    if (c == '"' || c == '\\') {
      dst[o++] = '\\';
      dst[o++] = (char)c;
    } else if (c == '\n') {
      dst[o++] = '\\';
      dst[o++] = 'n';
    } else if (c < 0x20) {
      o += (size_t)snprintf(dst + o, dst_n - o, "\\u%04x", c);
    } else {
      dst[o++] = (char)c;
    }
  }
  dst[o] = 0;
}

static const char *find_key(const char *json, const char *key) {
  char pattern[128];
  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  const char *p = strstr(json, pattern);
  if (!p)
    return NULL;
  p += strlen(pattern);
  while (*p == ' ' || *p == '\t')
    ++p;
  if (*p != ':')
    return NULL;
  ++p;
  while (*p == ' ' || *p == '\t')
    ++p;
  return p;
}

static int json_int(const char *json, const char *key, long long *out) {
  const char *p = find_key(json, key);
  if (!p)
    return 0;
  if (!strncmp(p, "true", 4)) {
    *out = 1;
    return 1;
  }
  if (!strncmp(p, "false", 5)) {
    *out = 0;
    return 1;
  }
  char *end = NULL;
  *out = strtoll(p, &end, 10);
  return end != p;
}

static int json_str(const char *json, const char *key, char *buf, size_t n) {
  const char *p = find_key(json, key);
  if (!p || *p != '"')
    return 0;
  ++p;
  size_t o = 0;
  while (*p && *p != '"' && o + 1 < n) {
    if (*p == '\\' && p[1]) {
      ++p;
      if (*p == 'n')
        buf[o++] = '\n';
      else
        buf[o++] = *p;
      ++p;
      continue;
    }
    buf[o++] = *p++;
  }
  buf[o] = 0;
  return 1;
}

static void emit_err(const char *msg) {
  char esc[512];
  json_escape(msg, esc, sizeof(esc));
  printf("{\"ok\":false,\"error\":\"%s\"}\n", esc);
  fflush(stdout);
}

static int rime_init(const char *line) {
  char home[kPathMax], shared[kPathMax], user[kPathMax], logdir[kPathMax];
  char schema[128], app[128];
  if (!json_str(line, "home", home, sizeof(home)) ||
      !json_str(line, "shared_data_dir", shared, sizeof(shared)) ||
      !json_str(line, "user_data_dir", user, sizeof(user)) ||
      !json_str(line, "log_dir", logdir, sizeof(logdir))) {
    emit_err("init missing paths");
    return 0;
  }
  if (!json_str(line, "schema", schema, sizeof(schema)))
    snprintf(schema, sizeof(schema), "luna_pinyin");
  if (!json_str(line, "app_name", app, sizeof(app)))
    snprintf(app, sizeof(app), "rime.squirrel.latency-probe");
  long long include_text = 0;
  json_int(line, "include_text", &include_text);
  g_include_text = include_text != 0;
  snprintf(g_schema, sizeof(g_schema), "%s", schema);

  if (setenv("HOME", home, 1) != 0) {
    emit_err("setenv HOME failed");
    return 0;
  }

  g_api = rime_get_api();
  if (!g_api) {
    emit_err("rime_get_api failed");
    return 0;
  }

  RIME_STRUCT(RimeTraits, traits);
  traits.shared_data_dir = shared;
  traits.user_data_dir = user;
  traits.log_dir = logdir;
  traits.app_name = app;
  traits.min_log_level = 2;
  traits.distribution_name = "Squirrel";
  traits.distribution_code_name = "Squirrel";
  traits.distribution_version = "latency-probe";

  uint64_t t0 = mono_ns();
  g_api->setup(&traits);
  g_api->deployer_initialize(&traits);
  if (!g_api->prebuild() || !g_api->deploy()) {
    emit_err("rime deploy failed");
    return 0;
  }
  g_api->initialize(&traits);
  uint64_t t1 = mono_ns();

  g_session = g_api->create_session();
  if (!g_session) {
    emit_err("create_session failed");
    return 0;
  }
  if (RIME_API_AVAILABLE(g_api, select_schema))
    g_api->select_schema(g_session, g_schema);
  g_api->set_option(g_session, "zh_hans", True);
  g_api->set_option(g_session, "simplification", True);

  if (!g_api->find_module("llm_rerank")) {
    emit_err("llm_rerank module not loaded");
    return 0;
  }

  g_inited = 1;
  printf("{\"ok\":true,\"op\":\"init\",\"deploy_ns\":%" PRIu64
         ",\"session\":%" PRIu64 ",\"version\":\"%s\"}\n",
         t1 - t0, (uint64_t)g_session,
         g_api->get_version() ? g_api->get_version() : "");
  fflush(stdout);
  return 1;
}

static void emit_row(const char *op,
                     long long seq,
                     uint64_t scheduled_ns,
                     uint64_t arrival_ns,
                     uint64_t handler_ns,
                     uint64_t process_key_ns,
                     uint64_t get_context_ns,
                     uint64_t get_commit_ns,
                     int handled,
                     int composing,
                     int preedit_bytes,
                     int num_candidates,
                     int commit_bytes,
                     const char *preedit,
                     const char *commit,
                     const char *candidates_json) {
  /* Host IMK queue is not present in this librime-only harness. The
     in-process delay from line arrival to handler entry is parse overhead. */
  int64_t queue_ns = 0;
  if (handler_ns >= arrival_ns)
    queue_ns = (int64_t)(handler_ns - arrival_ns);
  uint64_t update_ns = process_key_ns + get_context_ns + get_commit_ns;
  printf("{\"ok\":true,\"op\":\"%s\",\"seq\":%lld,"
         "\"scheduled_ns\":%" PRIu64 ",\"arrival_ns\":%" PRIu64
         ",\"handler_ns\":%" PRIu64 ",\"queue_delay_ns\":%" PRId64
         ",\"process_key_ns\":%" PRIu64 ",\"get_context_ns\":%" PRIu64
         ",\"get_commit_ns\":%" PRIu64 ",\"event_to_candidate_ns\":%" PRIu64
         ",\"handled\":%s,\"composing\":%s,\"preedit_bytes\":%d,"
         "\"num_candidates\":%d,\"commit_bytes\":%d",
         op, seq, scheduled_ns, arrival_ns, handler_ns, queue_ns,
         process_key_ns, get_context_ns, get_commit_ns, update_ns,
         handled ? "true" : "false", composing ? "true" : "false",
         preedit_bytes, num_candidates, commit_bytes);
  if (g_include_text) {
    char pe[kTextMax], ct[kTextMax];
    json_escape(preedit ? preedit : "", pe, sizeof(pe));
    json_escape(commit ? commit : "", ct, sizeof(ct));
    printf(",\"preedit\":\"%s\",\"commit\":\"%s\",\"candidates\":%s", pe, ct,
           candidates_json ? candidates_json : "[]");
  }
  printf("}\n");
  fflush(stdout);
}

static int handle_key_like(const char *op, const char *line, uint64_t arrival) {
  if (!g_inited) {
    emit_err("not initialized");
    return 0;
  }
  long long seq = 0, code = 0, mask = 0, scheduled = 0, index = 0;
  json_int(line, "seq", &seq);
  json_int(line, "scheduled_ns", &scheduled);
  uint64_t handler = mono_ns();
  uint64_t t_pk0 = 0, t_pk1 = 0, t_gc0 = 0, t_gc1 = 0, t_cm0 = 0, t_cm1 = 0;
  int handled = 1;

  if (strcmp(op, "key") == 0) {
    if (!json_int(line, "code", &code)) {
      emit_err("key missing code");
      return 0;
    }
    json_int(line, "mask", &mask);
    t_pk0 = mono_ns();
    handled = g_api->process_key(g_session, (int)code, (int)mask) ? 1 : 0;
    t_pk1 = mono_ns();
  } else if (strcmp(op, "select") == 0) {
    if (!json_int(line, "index", &index)) {
      emit_err("select missing index");
      return 0;
    }
    t_pk0 = mono_ns();
    if (RIME_API_AVAILABLE(g_api, select_candidate_on_current_page))
      handled = g_api->select_candidate_on_current_page(g_session,
                                                        (size_t)index)
                    ? 1
                    : 0;
    else
      handled = g_api->select_candidate(g_session, (size_t)index) ? 1 : 0;
    t_pk1 = mono_ns();
  } else if (strcmp(op, "commit") == 0) {
    t_pk0 = mono_ns();
    handled = g_api->commit_composition(g_session) ? 1 : 0;
    t_pk1 = mono_ns();
  } else if (strcmp(op, "clear") == 0) {
    t_pk0 = mono_ns();
    g_api->clear_composition(g_session);
    t_pk1 = mono_ns();
    handled = 1;
  } else if (strcmp(op, "context") == 0) {
    t_pk0 = t_pk1 = mono_ns();
  } else {
    emit_err("unknown key-like op");
    return 0;
  }

  char commit_text[kTextMax];
  commit_text[0] = 0;
  t_cm0 = mono_ns();
  RIME_STRUCT(RimeCommit, commit);
  if (g_api->get_commit(g_session, &commit)) {
    if (commit.text)
      snprintf(commit_text, sizeof(commit_text), "%s", commit.text);
    g_api->free_commit(&commit);
  }
  t_cm1 = mono_ns();

  char preedit[kTextMax];
  preedit[0] = 0;
  char cand_json[kTextMax];
  snprintf(cand_json, sizeof(cand_json), "[]");
  int composing = 0, preedit_bytes = 0, num_candidates = 0;
  t_gc0 = mono_ns();
  RIME_STRUCT(RimeContext, ctx);
  if (g_api->get_context(g_session, &ctx)) {
    if (ctx.composition.preedit) {
      snprintf(preedit, sizeof(preedit), "%s", ctx.composition.preedit);
      preedit_bytes = (int)strlen(preedit);
    }
    composing = ctx.composition.length > 0;
    num_candidates = ctx.menu.num_candidates;
    if (g_include_text && ctx.menu.candidates && num_candidates > 0) {
      size_t o = 0;
      cand_json[o++] = '[';
      int limit = num_candidates < 8 ? num_candidates : 8;
      for (int i = 0; i < limit && o + 8 < sizeof(cand_json); ++i) {
        char esc[256];
        json_escape(ctx.menu.candidates[i].text ? ctx.menu.candidates[i].text
                                                : "",
                    esc, sizeof(esc));
        o += (size_t)snprintf(cand_json + o, sizeof(cand_json) - o, "%s\"%s\"",
                              i ? "," : "", esc);
      }
      if (o + 1 < sizeof(cand_json)) {
        cand_json[o++] = ']';
        cand_json[o] = 0;
      }
    }
    g_api->free_context(&ctx);
  }
  t_gc1 = mono_ns();

  emit_row(op, seq, (uint64_t)scheduled, arrival, handler, t_pk1 - t_pk0,
           t_gc1 - t_gc0, t_cm1 - t_cm0, handled, composing, preedit_bytes,
           num_candidates, (int)strlen(commit_text), preedit, commit_text,
           cand_json);
  return 1;
}

static int handle_line(const char *line, uint64_t arrival) {
  char op[32];
  if (!json_str(line, "op", op, sizeof(op))) {
    emit_err("missing op");
    return 1;
  }
  if (strcmp(op, "init") == 0)
    return rime_init(line) ? 1 : 0;
  if (strcmp(op, "key") == 0 || strcmp(op, "select") == 0 ||
      strcmp(op, "commit") == 0 || strcmp(op, "clear") == 0 ||
      strcmp(op, "context") == 0)
    return handle_key_like(op, line, arrival);
  if (strcmp(op, "overhead") == 0) {
    long long n = 10000;
    json_int(line, "n", &n);
    uint64_t t0 = mono_ns();
    volatile uint64_t acc = 0;
    for (long long i = 0; i < n; ++i)
      acc ^= mono_ns();
    uint64_t t1 = mono_ns();
    printf("{\"ok\":true,\"op\":\"overhead\",\"n\":%lld,\"total_ns\":%" PRIu64
           ",\"acc\":%" PRIu64 "}\n",
           n, t1 - t0, (uint64_t)acc);
    fflush(stdout);
    return 1;
  }
  if (strcmp(op, "shutdown") == 0) {
    if (g_session && g_api)
      g_api->destroy_session(g_session);
    if (g_api)
      g_api->finalize();
    g_session = 0;
    g_inited = 0;
    printf("{\"ok\":true,\"op\":\"shutdown\"}\n");
    fflush(stdout);
    return 0;
  }
  emit_err("unknown op");
  return 1;
}

int main(void) {
  char line[kLineMax];
  setvbuf(stdin, NULL, _IOLBF, 0);
  setvbuf(stdout, NULL, _IOLBF, 0);
  while (fgets(line, sizeof(line), stdin)) {
    uint64_t arrival = mono_ns();
    size_t n = strlen(line);
    while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
      line[--n] = 0;
    if (!n)
      continue;
    if (!handle_line(line, arrival))
      break;
  }
  if (g_inited && g_api) {
    if (g_session)
      g_api->destroy_session(g_session);
    g_api->finalize();
  }
  return 0;
}
