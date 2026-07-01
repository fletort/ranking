from ranking.plugins.breizhchrono.resultdetail import extract_result_detail


def test_extract_result_detail_returns_expected_fields() -> None:
    html = """
    <div class="container container-fluid pt-3 center-wrapper">
      <div class="row mt-2">
        <div class="col-12 col-md-6">
          <h1 class="title pb-2 text-center">CURIE Marie (N°0110)</h1>
          <div id="identity" class="mt-3 rounded-black">
            <div class="row">
              <span id="sex" title="Sexe : F">F</span>
              <span id="nat" title="Nationalité : FRA"><img src="/images/live-flags/FRA.jpg"></span>
              <span id="birth" title="Année de naissance : 1912">1912</span>
              <span id="categ" title="Catégorie : SE">SE</span>
            </div>
          </div>
        </div>
      </div>
      <div class="row mt-3 mt-md-4 justify-content-center">
        <div class="bloc-classement">
          <span class="classementTitle">Classement<br/>général</span>
          <span class="classementIndex"><img alt="1"/></span>
          <span class="classementTitle">/ 2134</span>
        </div>
        <div class="bloc-classement">
          <span class="classementTitle">Classement<br/>catégorie</span>
          <span class="classementIndex"><img alt="2"/></span>
          <span class="classementTitle">/ 512</span>
        </div>
        <div class="bloc-classement">
          <span class="classementTitle">Classement<br/>Sexe</span>
          <span class="classementIndex"><img alt="3"/></span>
          <span class="classementTitle">/ 1068</span>
        </div>
        <div>
          <span class="timeTitle">Temps Officiel</span>
          <span class="timeValue">00:29:40</span>
        </div>
        <div>
          <span class="secondaryTime">Temps Réel</span>
          <span class="secondaryTime">00:29:41</span>
        </div>
      </div>
      <div class="table-responsive mt-4 d-none d-md-flex">
        <table class="">
          <thead class="">
          <tr>
            <th></th>
            <th>Temps</th>
            <th>Classement</th>
            <th>Classement catégorie</th>
          </tr>
          </thead>
          <tbody>
            <tr>
              <td>Natation</td>
              <td>00:24:11</td>
              <td>28ᵉ</td>
              <td>4ᵉ</td>
            </tr>
            <tr>
              <td>T1</td>
              <td>00:00:53</td>
              <td>16ᵉ</td>
              <td><img alt="2"></td>
            </tr>
            <tr>
              <td>VEL0</td>
              <td>00:49:14</td>
              <td><img alt="2"></td>
              <td><img alt="1"></td>
            </tr>

            <tr>
              <td>T2  CAP</td>
              <td>00:36:58</td>
              <td><img alt="1"></td>
              <td><img alt="1"></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    """

    result = extract_result_detail(html)

    assert result == {
        "name_bib": "CURIE Marie (N°0110)",
        "sex": "Sexe : F",
        "nationality": "Nationalité : FRA",
        "birth": "Année de naissance : 1912",
        "category": "Catégorie : SE",
        "global_ranks": [
            {
                "name": "Classement général",
                "total": "2134",
                "value": "1",
            },
            {
                "name": "Classement catégorie",
                "total": "512",
                "value": "2",
            },
            {
                "name": "Classement Sexe",
                "total": "1068",
                "value": "3",
            },
        ],
        "global_times": [
            {
                "name": "Temps Officiel",
                "value": "00:29:40",
            },
            {
                "name": "Temps Réel",
                "value": "00:29:41",
            },
        ],
        "other_ranktimes": [
            {
                "category_rank": "4ᵉ",
                "name": "Natation",
                "overall_rank": "28ᵉ",
                "time": "00:24:11",
            },
            {
                "category_rank": "2",
                "name": "T1",
                "overall_rank": "16ᵉ",
                "time": "00:00:53",
            },
            {
                "category_rank": "1",
                "name": "VEL0",
                "overall_rank": "2",
                "time": "00:49:14",
            },
            {
                "category_rank": "1",
                "name": "T2  CAP",
                "overall_rank": "1",
                "time": "00:36:58",
            },
        ],
    }


def test_extract_result_detail_handles_missing_data() -> None:
    assert extract_result_detail("<html><body></body></html>") == {
        "birth": "",
        "category": "",
        "global_ranks": [],
        "global_times": [],
        "name_bib": "",
        "nationality": "",
        "other_ranktimes": [],
        "sex": "",
    }
